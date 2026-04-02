import os
import json
import time
import threading
import eventlet
from copy import deepcopy

from config import (
    STATE_FILE, MEDIA_RUNTIME_FILE, LED_RUNTIME_FILE, AI_RUNTIME_FILE,
    ALARMS_FILE, JOB_STATE_FILE, RFID_MAP_FILE, STATE_SAVE_DEBOUNCE_SEC
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
}
DEFAULT_LED_RUNTIME = {
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
    payload = {
        "state": state, 
        "media_runtime": media_runtime, 
        "ai_runtime": ai_runtime, 
        "led_runtime": led_runtime
    }
    bus.cached_public_json = payload
    return payload

def build_admin_snapshot():
    payload = build_public_snapshot().copy()
    payload["jobs"] = get_jobs_list_sorted()
    payload["rfid_map"] = rfid_map
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

            # 2. Aggiornamenti WebSocket verso Vue.js (raggruppati)
            if "public" in to_emit:
                socketio.emit("public_snapshot", build_public_snapshot())
            if "admin" in to_emit:
                socketio.emit("admin_snapshot", build_admin_snapshot())
            if "jobs" in to_emit:
                socketio.emit("jobs_update", {"jobs": get_jobs_list_sorted()})

# Istanza globale utilizzata da tutto il progetto
bus = EventBus()

