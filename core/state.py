import os
import json
import time
import threading
import eventlet
from copy import deepcopy

from config import (
    STATE_FILE, MEDIA_RUNTIME_FILE, LED_RUNTIME_FILE, AI_RUNTIME_FILE,
    ALARMS_FILE, JOB_STATE_FILE, RFID_MAP_FILE, RFID_PROFILES_FILE,
    RSS_RUNTIME_FILE, STATE_SAVE_DEBOUNCE_SEC,
    OTA_STATE_FILE, BACKUP_DIR,
)
from core.extensions import socketio
from core.utils import log

_json_write_lock = threading.Lock()

def now_ts():
    return int(time.time())

# =========================================================
# LETTURA E SCRITTURA JSON (Thread-Safe)
# =========================================================
def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log(f"Errore lettura {path}: {e}", "warning")
    return deepcopy(default)

def save_json_direct(path, data):
    """Scrittura sicura: scrive su un file .tmp e poi lo rinomina, 
    così se salta la corrente non perdi i dati."""
    with _json_write_lock:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

# =========================================================
# VARIABILI DI STATO GLOBALI (In RAM)
# =========================================================
DEFAULT_STATE = {
    "initialized": True,
    "pin_enabled": True,
    "volume": 60,
    "lang": "it",
    # auth sub-dict (populated by api/auth.py on first login)
    "auth": None,
    # battery last reading (populated by hw/battery.py)
    "battery": None,
    # parental control
    "parental_control": {
        "enabled": False,
        "daily_limit_minutes": 120,
        "allow_from": "08:00",
        "allow_to": "20:30",
        "max_volume": 80,
    },
}
DEFAULT_MEDIA_RUNTIME = {
    "player_running": False,
    "player_mode": "idle",
    "current_volume": 60,
    "sleep_timer_target_ts": None,
    "current_file": None,
    "current_rfid_uid": None,
    "resume_position": None,
    # PR2: campi estesi
    "current_rfid": None,
    "current_profile_name": None,
    "current_mode": "idle",
    "current_media_path": None,
    "current_playlist": [],
    "playlist_index": 0,
    "rss_state": None,
}
DEFAULT_LED_RUNTIME = {
    # --- New PR3 fields ---
    "master_override_active": False,
    "current_source": "default",   # "default" | "master" | "rfid" | "ai"
    "current_rfid": None,          # UID of the active RFID profile driving LEDs
    "ai_state": None,              # Active AI state driving LEDs (idle/listening/…)
    "applied": {                   # Full assignment currently applied
        "enabled": True,
        "effect_id": "solid",
        "color": "#0000ff",
        "brightness": 70,
        "speed": 30,
        "params": {},
    },
    "last_updated_ts": 0,
    # --- Legacy fields kept for hw/led.py backward compatibility ---
    "master_enabled": True,
    "current_effect": "solid",
    "master_color": "#0000ff",
    "master_brightness": 70,
    "master_speed": 30,
}
DEFAULT_AI_RUNTIME = {"is_speaking": False, "is_thinking": False, "history": []}

state = load_json(STATE_FILE, DEFAULT_STATE)
media_runtime = load_json(MEDIA_RUNTIME_FILE, DEFAULT_MEDIA_RUNTIME)
led_runtime = load_json(LED_RUNTIME_FILE, DEFAULT_LED_RUNTIME)
ai_runtime = load_json(AI_RUNTIME_FILE, DEFAULT_AI_RUNTIME)
alarms_list = load_json(ALARMS_FILE, [])
jobs_state = load_json(JOB_STATE_FILE, {})
rfid_map = load_json(RFID_MAP_FILE, {})
rfid_profiles = load_json(RFID_PROFILES_FILE, {})
rss_runtime = load_json(RSS_RUNTIME_FILE, {})

# =========================================================
# FUNZIONI SNAPSHOT PER IL FRONTEND
# =========================================================
def get_jobs_list_sorted():
    now = now_ts()
    out = []
    for jid, job in jobs_state.items():
        finished = job.get("finished_ts") or job.get("end_ts", 0)
        if job.get("status") in ["done", "error", "canceled"] and (now - finished) > 86400:
            continue
        out.append(job)
    return sorted(out, key=lambda x: x.get("created_ts", x.get("start_ts", 0)), reverse=True)

def build_public_snapshot():
    # Se abbiamo già calcolato il JSON di recente, usiamo la cache!
    if bus.cached_public_json: 
        return bus.cached_public_json
    # Include standby state (in-memory, not persisted)
    try:
        from core.hardware import is_in_standby
        in_standby = is_in_standby()
    except Exception:
        in_standby = False
    payload = {
        "state": state, 
        "media_runtime": media_runtime, 
        "ai_runtime": ai_runtime, 
        "led_runtime": led_runtime,
        "in_standby": in_standby,
    }
    bus.cached_public_json = payload
    return payload

def build_admin_snapshot():
    payload = build_public_snapshot().copy()
    payload["jobs"] = get_jobs_list_sorted()
    payload["rfid_map"] = rfid_map
    payload["rfid_profiles"] = rfid_profiles
    payload["rss_runtime"] = rss_runtime

    # Include OTA state and backup count in admin snapshot
    try:
        import json as _json
        if os.path.exists(OTA_STATE_FILE):
            with open(OTA_STATE_FILE, "r", encoding="utf-8") as _f:
                _ota = _json.load(_f)
            _ota["running"] = _ota.get("status") == "running"
            payload["ota_state"] = _ota
        else:
            payload["ota_state"] = {"status": "idle", "running": False}
    except Exception:
        payload["ota_state"] = {"status": "idle", "running": False}

    try:
        if os.path.isdir(BACKUP_DIR):
            payload["backup_count"] = sum(
                1 for n in os.listdir(BACKUP_DIR)
                if os.path.isdir(os.path.join(BACKUP_DIR, n))
            )
        else:
            payload["backup_count"] = 0
    except Exception:
        payload["backup_count"] = 0

    return payload

# =========================================================
# L'EVENTBUS (Il vigile urbano dei dati)
# =========================================================
class EventBus:
    def __init__(self):
        self.lock = threading.Lock()
        self.dirty_files = set()
        self.cached_public_json = None
        self.cached_admin_json = None
        self.pending_emits = set()
        # Avviamo il worker in background
        eventlet.spawn(self._worker)

    def mark_dirty(self, file_type):
        """Segnala che un dato è cambiato in RAM e andrà salvato su SD."""
        with self.lock:
            self.dirty_files.add(file_type)
            self.cached_public_json = None # Invalida la cache

    def request_emit(self, event_type):
        """Segnala che bisogna avvisare il frontend Vue di un cambiamento."""
        with self.lock:
            self.pending_emits.add(event_type)

    def emit_notification(self, message, level="info"):
        """Invia un toast di notifica immediato al frontend."""
        socketio.emit("notification", {"message": message, "level": level})

    def _worker(self):
        """Ciclo infinito che ogni tot secondi esegue i salvataggi accumulati."""
        while True:
            eventlet.sleep(STATE_SAVE_DEBOUNCE_SEC)
            to_save = set()
            to_emit = set()
            with self.lock:
                to_save, self.dirty_files = self.dirty_files, set()
                to_emit, self.pending_emits = self.pending_emits, set()
            
            # 1. Scritture fisiche su SD Card (raggruppate)
            if "state" in to_save: save_json_direct(STATE_FILE, state)
            if "media" in to_save: save_json_direct(MEDIA_RUNTIME_FILE, media_runtime)
            if "led" in to_save: save_json_direct(LED_RUNTIME_FILE, led_runtime)
            if "ai" in to_save: save_json_direct(AI_RUNTIME_FILE, ai_runtime)
            if "alarms" in to_save: save_json_direct(ALARMS_FILE, alarms_list)
            if "rfid_profiles" in to_save: save_json_direct(RFID_PROFILES_FILE, rfid_profiles)
            if "rss" in to_save: save_json_direct(RSS_RUNTIME_FILE, rss_runtime)

            # 2. Aggiornamenti WebSocket verso Vue.js (raggruppati)
            if "public" in to_emit:
                socketio.emit("public_snapshot", build_public_snapshot())
            if "admin" in to_emit:
                socketio.emit("admin_snapshot", build_admin_snapshot())
            if "jobs" in to_emit:
                socketio.emit("jobs_update", {"jobs": get_jobs_list_sorted()})

# Istanza globale utilizzata da tutto il progetto
bus = EventBus()

