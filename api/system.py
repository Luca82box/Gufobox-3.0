import os
import json
import shutil
import threading
from datetime import datetime

from flask import Blueprint, request, jsonify
from core.state import media_runtime, alarms_list, bus, now_ts
from core.utils import run_cmd, t, log
from core.hardware import perform_standby
from config import BASE_DIR, BACKUP_DIR, OTA_LOG_FILE, OTA_STATE_FILE

# Creiamo il Blueprint per le rotte di sistema
system_bp = Blueprint('system', __name__)

# =========================================================
# HEALTH CHECK (usato dal HEALTHCHECK Docker)
# =========================================================
@system_bp.route("/ping", methods=["GET"])
def api_ping():
    """Endpoint minimale per health check."""
    return jsonify({"status": "ok"})


@system_bp.route("/system", methods=["POST"])
def api_system():
    data = request.get_json(silent=True) or {}
    azione = str(data.get("azione", "")).strip().lower()
    
    if azione == "standby":
        # Richiama la funzione hardware isolata che spegne le periferiche
        perform_standby()
        return jsonify({"status": "ok", "message": t("ok_standby")})
        
    elif azione == "reboot":
        log("Comando di riavvio ricevuto", "info")
        bus.emit_notification("Riavvio in corso... 🔄", "warning")
        run_cmd(["sudo", "reboot"])
        return jsonify({"status": "ok", "message": t("ok_reboot")})

    elif azione == "shutdown":
        log("Comando di spegnimento ricevuto", "info")
        bus.emit_notification("Spegnimento in corso... 🔌", "warning")
        run_cmd(["sudo", "shutdown", "-h", "now"])
        return jsonify({"status": "ok", "message": t("ok_shutdown")})
        
    return jsonify({"status": "ok"})

# =========================================================
# SLEEP TIMER (Spegnimento automatico)
# =========================================================
@system_bp.route("/system/sleep_timer", methods=["POST"])
def api_sleep_timer():
    data = request.get_json(silent=True) or {}
    minutes = data.get("minutes", 0)
    
    try:
        minutes = int(minutes)
    except ValueError:
        minutes = 0

    if minutes > 0:
        # Calcola il timestamp futuro in cui spegnersi
        media_runtime["sleep_timer_target_ts"] = now_ts() + (minutes * 60)
        bus.emit_notification(f"Spegnimento tra {minutes} minuti 🌙", "info")
        log(f"Sleep timer impostato a {minutes} minuti", "info")
    else:
        # Disattiva il timer
        media_runtime["sleep_timer_target_ts"] = None
        bus.emit_notification("Timer disattivato", "info")
        log("Sleep timer disattivato", "info")
        
    # Avvisa l'EventBus del cambiamento
    bus.mark_dirty("media")
    bus.request_emit("public")
    
    return jsonify({
        "status": "ok", 
        "sleep_timer_target_ts": media_runtime.get("sleep_timer_target_ts")
    })

# =========================================================
# SNOOZE (Posticipo Sveglia)
# =========================================================
@system_bp.route("/alarms/<alarm_id>/snooze", methods=["POST"])
def api_alarm_snooze(alarm_id):
    """
    Posticipa la sveglia di 10 minuti. 
    Questa rotta verrà chiamata anche dal demone dei pulsanti fisici (GPIO).
    """
    from core.media import stop_player # Import locale per evitare conflitti
    
    for a in alarms_list:
        if str(a.get("id")) == str(alarm_id):
            # Aggiunge 10 minuti all'orario attuale della sveglia
            a["minute"] = (a.get("minute", 0) + 10) % 60
            
            # Se scatta l'ora successiva
            if a["minute"] < 10: 
                a["hour"] = (a.get("hour", 0) + 1) % 24
            
            # Ferma la musica che sta suonando ora
            stop_player()
            
            # Salva e avvisa il frontend
            bus.mark_dirty("alarms")
            bus.request_emit("public")
            bus.emit_notification("Sveglia posposta di 10 minuti ⏰", "info")
            log(f"Sveglia {alarm_id} posposta alle {a['hour']:02d}:{a['minute']:02d}", "info")
            
            return jsonify({"status": "ok", "message": "Snoozed"})
            
    return jsonify({"error": "Sveglia non trovata"}), 404


# =========================================================
# OTA — Aggiornamento App / Sistema
# =========================================================

_ota_lock = threading.Lock()

# File/cartelle esclusi da backup e rollback
_BACKUP_EXCLUSIONS = {".git", "__pycache__", "node_modules", "data", ".env"}


def _ota_log(msg):
    """Scrive una riga nel file ota.log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(OTA_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        log(f"Errore scrittura ota.log: {e}", "warning")
    log(f"[OTA] {msg}", "info")


def _load_ota_state():
    if os.path.exists(OTA_STATE_FILE):
        try:
            with open(OTA_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"status": "idle", "mode": None, "started_at": None, "finished_at": None, "error": None}


def _save_ota_state(state_dict):
    try:
        from core.state import save_json_direct as _sj
        _sj(OTA_STATE_FILE, state_dict)
    except Exception as e:
        log(f"Errore salvataggio ota_state: {e}", "warning")


def _create_backup():
    """
    Crea un backup dell'app nella BACKUP_DIR.
    Esclude .git, __pycache__, node_modules e data/.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"gufobox_backup_{ts}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    _ota_log(f"Creazione backup in {backup_path}...")
    try:
        def _ignore(src, names):
            return {n for n in names if n in _BACKUP_EXCLUSIONS}
        shutil.copytree(BASE_DIR, backup_path, ignore=_ignore)
        _ota_log(f"Backup completato: {backup_name}")
        return backup_name
    except Exception as e:
        _ota_log(f"Errore backup: {e}")
        return None


def _run_ota(mode):
    """Esegue l'aggiornamento in un thread separato."""
    ota_state = _load_ota_state()
    ota_state["status"] = "running"
    ota_state["mode"] = mode
    ota_state["started_at"] = datetime.now().isoformat()
    ota_state["finished_at"] = None
    ota_state["error"] = None
    _save_ota_state(ota_state)

    try:
        backup_name = _create_backup()
        if not backup_name:
            raise RuntimeError("Backup fallito, aggiornamento annullato per sicurezza")

        if mode == "app":
            _ota_log("Modalità: aggiornamento app (git pull + pip install)")
            code, out, err = run_cmd(["git", "pull", "--ff-only"], cwd=BASE_DIR, timeout=120)
            _ota_log(f"git pull: code={code} out={out} err={err}")
            if code != 0:
                raise RuntimeError(f"git pull fallito: {err}")
            req_file = os.path.join(BASE_DIR, "requirements.txt")
            if os.path.exists(req_file):
                code, out, err = run_cmd(
                    ["pip", "install", "-r", req_file], cwd=BASE_DIR, timeout=180
                )
                _ota_log(f"pip install: code={code}")
                if code != 0:
                    _ota_log(f"Attenzione pip install: {err}")

        elif mode == "system_safe":
            _ota_log("Modalità: aggiornamento sistema (apt-get)")
            for cmd in [
                ["sudo", "apt-get", "update", "-y"],
                ["sudo", "apt-get", "full-upgrade", "-y"],
                ["sudo", "apt-get", "autoremove", "-y"],
            ]:
                code, out, err = run_cmd(cmd, timeout=300)
                _ota_log(f"{' '.join(cmd)}: code={code}")
                if code != 0:
                    _ota_log(f"Avviso: {err}")

        else:
            raise RuntimeError(f"Modalità OTA non supportata: {mode}")

        ota_state["status"] = "done"
        _ota_log("Aggiornamento completato con successo!")
        bus.emit_notification("Aggiornamento completato! ✅", "success")

    except Exception as e:
        ota_state["status"] = "error"
        ota_state["error"] = str(e)
        _ota_log(f"ERRORE OTA: {e}")
        bus.emit_notification(f"Errore aggiornamento: {e}", "error")
    finally:
        ota_state["finished_at"] = datetime.now().isoformat()
        _save_ota_state(ota_state)


@system_bp.route("/system/ota/start", methods=["POST"])
def api_ota_start():
    """
    Avvia un aggiornamento OTA in background.
    Payload: {"mode": "app" | "system_safe"}
    """
    if not _ota_lock.acquire(blocking=False):
        return jsonify({"error": "Un aggiornamento è già in corso"}), 409

    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "app")
    if mode not in ("app", "system_safe"):
        _ota_lock.release()
        return jsonify({"error": f"Modalità non supportata: {mode}. Usa 'app' o 'system_safe'"}), 400

    def _worker():
        try:
            _run_ota(mode)
        finally:
            _ota_lock.release()

    t_ota = threading.Thread(target=_worker, daemon=True)
    t_ota.start()
    bus.emit_notification(f"Aggiornamento avviato (modalità: {mode}) ⬆️", "info")
    return jsonify({"status": "started", "mode": mode})


@system_bp.route("/system/ota/status", methods=["GET"])
def api_ota_status():
    """Restituisce lo stato attuale dell'OTA."""
    return jsonify(_load_ota_state())


@system_bp.route("/system/ota/log", methods=["GET"])
def api_ota_log():
    """Restituisce il contenuto del log OTA."""
    if not os.path.exists(OTA_LOG_FILE):
        return jsonify({"log": ""})
    try:
        with open(OTA_LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"log": content})
    except Exception as e:
        log(f"Errore lettura ota.log: {e}", "warning")
        return jsonify({"error": "Impossibile leggere il log OTA"}), 500


# =========================================================
# BACKUP / ROLLBACK
# =========================================================

@system_bp.route("/system/backups", methods=["GET"])
def api_backups_list():
    """Elenca i backup disponibili."""
    backups = []
    if os.path.isdir(BACKUP_DIR):
        for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
            bpath = os.path.join(BACKUP_DIR, name)
            if os.path.isdir(bpath):
                stat = os.stat(bpath)
                backups.append({
                    "name": name,
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "size_mb": round(
                        sum(
                            os.path.getsize(os.path.join(dp, f))
                            for dp, dn, fns in os.walk(bpath)
                            for f in fns
                        ) / (1024 * 1024),
                        2,
                    ),
                })
    return jsonify({"backups": backups})


@system_bp.route("/system/backups/<backup_name>", methods=["DELETE"])
def api_backup_delete(backup_name):
    """Elimina un backup specifico."""
    # Sicurezza: costruiamo il path dal listing fidato (non dall'input utente)
    safe_name = os.path.basename(backup_name)
    available = os.listdir(BACKUP_DIR) if os.path.isdir(BACKUP_DIR) else []
    trusted_name = next((x for x in available if x == safe_name), None)
    if trusted_name is None:
        return jsonify({"error": "Backup non trovato"}), 404
    bpath = os.path.join(BACKUP_DIR, trusted_name)
    if not os.path.isdir(bpath):
        return jsonify({"error": "Backup non trovato"}), 404
    try:
        shutil.rmtree(bpath)
        log(f"Backup '{trusted_name}' eliminato", "info")
        return jsonify({"status": "ok"})
    except Exception as e:
        log(f"Errore eliminazione backup '{trusted_name}': {e}", "warning")
        return jsonify({"error": "Errore durante l'eliminazione del backup"}), 500


@system_bp.route("/system/rollback", methods=["POST"])
def api_rollback():
    """
    Ripristina l'app da un backup.
    Payload: {"backup_name": "gufobox_backup_20260101_120000"}
    Nota: crea prima un backup del corrente, poi ripristina.
    """
    data = request.get_json(silent=True) or {}
    backup_name = os.path.basename(data.get("backup_name", ""))
    if not backup_name:
        return jsonify({"error": "backup_name mancante"}), 400

    # Sicurezza: costruiamo il path dal listing fidato (non dall'input utente)
    available = os.listdir(BACKUP_DIR) if os.path.isdir(BACKUP_DIR) else []
    trusted_name = next((x for x in available if x == backup_name), None)
    if trusted_name is None:
        return jsonify({"error": "Backup non trovato"}), 404
    bpath = os.path.join(BACKUP_DIR, trusted_name)
    if not os.path.isdir(bpath):
        return jsonify({"error": "Backup non trovato"}), 404

    def _do_rollback():
        _ota_log(f"Rollback avviato da backup: {trusted_name}")
        safety_backup = _create_backup()
        _ota_log(f"Backup di sicurezza pre-rollback: {safety_backup}")

        # Sovrascrivi i file dell'app con quelli del backup
        # (escludi .git, data/, __pycache__)
        errors = []
        for item in os.listdir(bpath):
            if item in _BACKUP_EXCLUSIONS:
                continue
            src = os.path.join(bpath, item)
            dst = os.path.join(BASE_DIR, item)
            try:
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except Exception as e:
                errors.append(str(e))
                _ota_log(f"Errore copia {item}: {e}")

        if errors:
            _ota_log(f"Rollback completato con {len(errors)} errori.")
            bus.emit_notification("Rollback completato con avvisi ⚠️", "warning")
        else:
            _ota_log("Rollback completato con successo!")
            bus.emit_notification("Rollback completato! ✅ Riavvia per applicare le modifiche.", "success")

    rb_thread = threading.Thread(target=_do_rollback, daemon=True)
    rb_thread.start()
    return jsonify({"status": "started", "backup_name": trusted_name})
