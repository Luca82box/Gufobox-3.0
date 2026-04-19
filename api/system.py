import io
import os
import json
import shutil
import tarfile
import tempfile
import threading
import zipfile
from datetime import datetime

import eventlet
from flask import Blueprint, request, jsonify
from core.state import media_runtime, led_runtime, alarms_list, alarms_lock, bus, now_ts
from core.utils import run_cmd, t, log
from core.hardware import perform_standby, is_in_standby, get_standby_state
from core.event_log import log_event
from config import (
    BASE_DIR, BACKUP_DIR, OTA_LOG_FILE, OTA_STATE_FILE,
    OTA_STAGING_DIR, OTA_MAX_PACKAGE_BYTES,
)

# Creiamo il Blueprint per le rotte di sistema
system_bp = Blueprint('system', __name__)

# =========================================================
# HEALTH CHECK (usato dal HEALTHCHECK Docker)
# =========================================================
@system_bp.route("/ping", methods=["GET"])
@system_bp.route("/health", methods=["GET"])
def api_ping():
    """Endpoint minimale per health check."""
    return jsonify({"status": "ok"})


@system_bp.route("/system", methods=["POST"])
def api_system():
    data = request.get_json(silent=True) or {}
    azione = str(data.get("azione", "")).strip().lower()
    
    if azione == "standby":
        # Richiama la funzione hardware isolata che spegne le periferiche
        log_event("standby", "info", "Standby avviato da admin")
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

    return jsonify({"error": "Azione non riconosciuta. Valori consentiti: standby, reboot, shutdown"}), 400


# =========================================================
# CONNETTIVITÀ
# =========================================================
@system_bp.route("/system/connectivity", methods=["GET"])
def api_system_connectivity():
    """Ritorna lo stato della connettività internet e OpenAI."""
    from core.connectivity import has_internet, has_openai
    internet = has_internet()
    openai_ok = has_openai()
    return jsonify({"internet": internet, "openai": openai_ok})


# =========================================================
# MODALITÀ NOTTE
# =========================================================

# Stato in-memory per salvare/ripristinare LED e volume precedenti
_night_mode_state = {
    "active": False,
    "prev_led": None,
    "prev_volume": None,
}

@system_bp.route("/system/night_mode", methods=["POST"])
def api_night_mode():
    """
    Attiva/disattiva la modalità notte.
    Payload: {"enabled": true|false}
    Quando attivata: LED breathing caldo (#ff8833), volume a 25%.
    Quando disattivata: ripristina stato precedente.
    """
    from api.led import load_led_master, save_led_master, refresh_effective_led

    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", True))

    if enabled:
        # Salva lo stato corrente LED e volume
        _night_mode_state["prev_led"] = dict(load_led_master())
        _night_mode_state["prev_volume"] = media_runtime.get("current_volume", 60)

        # Imposta LED: breathing caldo
        night_master = {
            "enabled": True,
            "override_active": True,
            "settings": {
                "enabled": True,
                "effect_id": "breathing",
                "color": "#ff8833",
                "brightness": 20,
                "speed": 15,
                "params": {},
            },
        }
        save_led_master(night_master)
        refresh_effective_led()

        # Abbassa volume a 25%
        run_cmd(["amixer", "sset", "Master", "25%"])
        media_runtime["current_volume"] = 25
        bus.mark_dirty("media")

        _night_mode_state["active"] = True
        bus.emit_notification("Modalità Notte attivata 🌙", "info")
        log("Modalità notte attivata", "info")

        return jsonify({"status": "ok", "night_mode": True})

    else:
        # Ripristina LED precedente
        if _night_mode_state.get("prev_led"):
            save_led_master(_night_mode_state["prev_led"])
            refresh_effective_led()

        # Ripristina volume precedente
        prev_vol = _night_mode_state.get("prev_volume", 60)
        run_cmd(["amixer", "sset", "Master", f"{prev_vol}%"])
        media_runtime["current_volume"] = prev_vol
        bus.mark_dirty("media")

        _night_mode_state["active"] = False
        _night_mode_state["prev_led"] = None
        _night_mode_state["prev_volume"] = None
        bus.emit_notification("Modalità Notte disattivata ☀️", "info")
        log("Modalità notte disattivata", "info")

        return jsonify({"status": "ok", "night_mode": False})


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
    Posticipa la sveglia di 5 minuti. 
    Questa rotta verrà chiamata anche dal demone dei pulsanti fisici (GPIO).
    """
    from core.media import stop_player # Import locale per evitare conflitti
    
    with alarms_lock:
        for a in alarms_list:
            if str(a.get("id")) == str(alarm_id):
                # Aggiunge 5 minuti all'orario attuale della sveglia
                a["minute"] = (a.get("minute", 0) + 5) % 60

                # Se scatta l'ora successiva
                if a["minute"] < 5:
                    a["hour"] = (a.get("hour", 0) + 1) % 24
                # Ferma la musica che sta suonando ora
                stop_player()
                try:
                    from core.hardware import wake_from_standby
                    wake_from_standby("button")
                except Exception:
                    pass

                # Salva e avvisa il frontend
                bus.mark_dirty("alarms")
                bus.request_emit("public")
                bus.emit_notification("Sveglia posposta di 5 minuti ⏰", "info")
                log(f"Sveglia {alarm_id} posposta alle {a['hour']:02d}:{a['minute']:02d}", "info")

                return jsonify({"status": "ok", "message": "Snoozed"})
            
    return jsonify({"error": "Sveglia non trovata"}), 404


# =========================================================
# OTA — Aggiornamento App / Sistema
# =========================================================

_ota_lock = threading.Lock()

# File/cartelle esclusi da backup e rollback
_BACKUP_EXCLUSIONS = {".git", "__pycache__", "node_modules", "data", ".env"}
OTA_UPLOAD_CHUNK_SIZE = 64 * 1024


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


_OTA_STATE_DEFAULT = {
    "running": False,
    "status": "idle",
    "mode": None,
    "started_at": None,
    "finished_at": None,
    "progress_percent": None,
    "description": None,
    "error": None,
    "last_error": None,
    # OTA-from-file fields
    "staged_filename": None,
    "staged_at": None,
}


def _load_ota_state():
    if os.path.exists(OTA_STATE_FILE):
        try:
            with open(OTA_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Backfill any missing keys from the default (schema migration)
            for k, v in _OTA_STATE_DEFAULT.items():
                if k not in data:
                    data[k] = v
            # Derive `running` from status so callers can always rely on it
            data["running"] = data.get("status") == "running"
            return data
        except Exception:
            pass
    return dict(_OTA_STATE_DEFAULT)


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
    ota_state.update({
        "running": True,
        "status": "running",
        "mode": mode,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "progress_percent": 0,
        "description": "Avvio aggiornamento...",
        "error": None,
        "last_error": None,
    })
    _save_ota_state(ota_state)
    log_event("ota", "info", f"OTA avviato (modalità: {mode})", {"mode": mode})

    def _progress(pct, desc):
        ota_state["progress_percent"] = pct
        ota_state["description"] = desc
        _save_ota_state(ota_state)
        _ota_log(f"[{pct}%] {desc}")

    try:
        _progress(5, "Creazione backup pre-aggiornamento...")
        backup_name = _create_backup()
        if not backup_name:
            raise RuntimeError("Backup fallito, aggiornamento annullato per sicurezza")
        _progress(15, f"Backup creato: {backup_name}")

        if mode == "app":
            git_dir = os.path.join(BASE_DIR, ".git")
            if shutil.which("git") is None:
                raise RuntimeError("OTA app non disponibile: git non è installato nel container")
            if not os.path.isdir(git_dir):
                raise RuntimeError("OTA app non disponibile: repository .git assente; usa OTA da file in Docker")
            _progress(20, "Modalità app — git pull in corso...")
            code, out, err = run_cmd(["git", "pull", "--ff-only"], cwd=BASE_DIR, timeout=120)
            _ota_log(f"git pull: code={code} out={out} err={err}")
            if code != 0:
                raise RuntimeError(f"git pull fallito: {err}")
            _progress(60, "git pull completato — installazione dipendenze...")
            req_file = os.path.join(BASE_DIR, "requirements.txt")
            if os.path.exists(req_file):
                code, out, err = run_cmd(
                    ["pip", "install", "-r", req_file], cwd=BASE_DIR, timeout=180
                )
                _ota_log(f"pip install: code={code}")
                if code != 0:
                    _ota_log(f"Attenzione pip install: {err}")
            _progress(90, "Dipendenze aggiornate")

        elif mode == "system_safe":
            steps = [
                (["sudo", "apt-get", "update", "-y"], 30, "apt-get update..."),
                (["sudo", "apt-get", "full-upgrade", "-y"], 70, "apt-get full-upgrade..."),
                (["sudo", "apt-get", "autoremove", "-y"], 90, "apt-get autoremove..."),
            ]
            for cmd, pct, desc in steps:
                _progress(pct - 10, desc)
                code, out, err = run_cmd(cmd, timeout=300)
                _ota_log(f"{' '.join(cmd)}: code={code}")
                if code != 0:
                    _ota_log(f"Avviso: {err}")
                _progress(pct, f"Completato: {' '.join(cmd[:3])}")

        else:
            raise RuntimeError(f"Modalità OTA non supportata: {mode}")

        ota_state["status"] = "done"
        ota_state["running"] = False
        ota_state["progress_percent"] = 100
        ota_state["description"] = "Aggiornamento completato con successo!"
        _ota_log("Aggiornamento completato con successo!")
        bus.emit_notification("Aggiornamento completato! ✅", "success")
        log_event("ota", "info", f"OTA completato con successo (modalità: {mode})", {"mode": mode})

    except Exception as e:
        ota_state["status"] = "error"
        ota_state["running"] = False
        ota_state["error"] = str(e)
        ota_state["last_error"] = str(e)
        ota_state["description"] = f"Errore: {e}"
        _ota_log(f"ERRORE OTA: {e}")
        bus.emit_notification(f"Errore aggiornamento: {e}", "error")
        log_event("ota", "error", f"OTA fallito (modalità: {mode}): {e}", {"mode": mode, "error": str(e)})
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

    eventlet.spawn_n(_worker)
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
        log_event("ota", "info", f"Backup eliminato: {trusted_name}", {"backup_name": trusted_name})
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
            log_event("ota", "warning", f"Rollback da {trusted_name} completato con {len(errors)} errori", {"backup_name": trusted_name, "errors": errors})
        else:
            _ota_log("Rollback completato con successo!")
            bus.emit_notification("Rollback completato! ✅ Riavvia per applicare le modifiche.", "success")
            log_event("ota", "info", f"Rollback completato con successo da {trusted_name}", {"backup_name": trusted_name})

    eventlet.spawn_n(_do_rollback)
    return jsonify({"status": "started", "backup_name": trusted_name})


# =========================================================
# OTA DA FILE — Upload, validazione, apply
# =========================================================

#: Estensioni accettate per i package OTA
_OTA_ALLOWED_EXTENSIONS = {".zip", ".tar.gz"}

#: File/dir che devono esistere nell'archivio per considerarlo un'app valida
_OTA_PACKAGE_REQUIRED = {"main.py"}

#: Path di destinazione che l'apply può toccare (esclude data/, .git, node_modules)
_OTA_APPLY_EXCLUSIONS = _BACKUP_EXCLUSIONS


def _ota_package_extension(filename: str):
    """
    Return the allowed extension (.zip or .tar.gz) or None if not recognised.
    Matching is case-insensitive.
    """
    name = filename.lower()
    if name.endswith(".tar.gz"):
        return ".tar.gz"
    if name.endswith(".zip"):
        return ".zip"
    return None


def _validate_archive(path: str, ext: str):
    """
    Validate a staged archive.

    Returns (ok: bool, error_message: str | None).

    Checks:
    - No path traversal (absolute paths or `..` components)
    - At least one required file present (main.py)
    - No member that would write outside the expected structure
    """
    members = []
    try:
        if ext == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                members = zf.namelist()
        elif ext == ".tar.gz":
            with tarfile.open(path, "r:gz") as tf:
                members = tf.getnames()
        else:
            return False, f"Estensione non supportata: {ext}"
    except (zipfile.BadZipFile, tarfile.TarError, Exception) as e:
        return False, f"Archivio corrotto o illeggibile: {e}"

    # Path traversal check
    for m in members:
        norm = os.path.normpath(m)
        if os.path.isabs(norm) or norm.startswith(".."):
            return False, f"Path traversal rilevato nel package: {m!r}"

    # Check for a top-level prefix (common: everything under "gufobox/", strip it)
    prefixes = set()
    for m in members:
        parts = m.replace("\\", "/").split("/", 1)
        if len(parts) > 1:
            prefixes.add(parts[0])

    stripped_names = set()
    if len(prefixes) == 1:
        # All members share a common top dir — strip it
        prefix = next(iter(prefixes)) + "/"
        for m in members:
            stripped_names.add(m[len(prefix):] if m.startswith(prefix) else m)
    else:
        stripped_names = set(members)

    # Check required files
    for req in _OTA_PACKAGE_REQUIRED:
        if req not in stripped_names:
            return False, (
                f"Package non valido: file richiesto '{req}' non trovato. "
                f"Il package deve contenere almeno: {', '.join(sorted(_OTA_PACKAGE_REQUIRED))}"
            )

    return True, None


def _apply_archive(staged_path: str, ext: str, dest_dir: str):
    """
    Extract the archive to a temp dir, then copy files to dest_dir.

    Returns (ok: bool, error_message: str | None, files_copied: int).
    Skips files in _OTA_APPLY_EXCLUSIONS.
    """
    with tempfile.TemporaryDirectory(prefix="gufobox_ota_apply_") as tmp:
        # Extract
        try:
            if ext == ".zip":
                with zipfile.ZipFile(staged_path, "r") as zf:
                    zf.extractall(tmp)
            elif ext == ".tar.gz":
                with tarfile.open(staged_path, "r:gz") as tf:
                    tf.extractall(tmp)
        except Exception as e:
            return False, f"Errore estrazione archivio: {e}", 0

        # Detect optional common top-level prefix
        top_items = os.listdir(tmp)
        src_root = tmp
        if len(top_items) == 1 and os.path.isdir(os.path.join(tmp, top_items[0])):
            src_root = os.path.join(tmp, top_items[0])

        # Copy each item (skip exclusions)
        errors = []
        files_copied = 0
        for item in os.listdir(src_root):
            if item in _OTA_APPLY_EXCLUSIONS:
                continue
            src = os.path.join(src_root, item)
            dst = os.path.join(dest_dir, item)
            try:
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                files_copied += 1
            except Exception as e:
                errors.append(f"{item}: {e}")

        if errors:
            return False, "Errori durante la copia: " + "; ".join(errors), files_copied

        return True, None, files_copied


def _run_ota_file(staged_path: str, staged_filename: str, ext: str):
    """Execute the OTA-from-file apply flow in a worker thread."""
    ota_state = _load_ota_state()
    ota_state.update({
        "running": True,
        "status": "validating",
        "mode": "file",
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "progress_percent": 0,
        "description": "Validazione package...",
        "error": None,
        "last_error": None,
        "staged_filename": staged_filename,
    })
    _save_ota_state(ota_state)
    log_event("ota", "info", "OTA da file: validazione avviata", {"filename": staged_filename})

    def _progress(pct, desc):
        ota_state["progress_percent"] = pct
        ota_state["description"] = desc
        _save_ota_state(ota_state)
        _ota_log(f"[{pct}%] {desc}")

    try:
        # 1) Validate
        _progress(5, "Validazione archivio in corso...")
        ok, err_msg = _validate_archive(staged_path, ext)
        if not ok:
            raise RuntimeError(f"Package non valido: {err_msg}")
        log_event("ota", "info", "OTA da file: validazione OK", {"filename": staged_filename})
        _progress(15, "Validazione completata — creazione backup pre-apply...")

        # 2) Backup
        ota_state["status"] = "applying"
        _save_ota_state(ota_state)
        backup_name = _create_backup()
        if not backup_name:
            raise RuntimeError("Backup fallito, apply annullato per sicurezza")
        _progress(30, f"Backup creato: {backup_name}")

        # 3) Apply
        _progress(40, "Applicazione package in corso...")
        ok, err_msg, files_copied = _apply_archive(staged_path, ext, BASE_DIR)
        if not ok:
            raise RuntimeError(f"Apply fallito: {err_msg}")
        _progress(90, f"Package applicato ({files_copied} elementi copiati)")

        # 4) Done
        ota_state["status"] = "success"
        ota_state["running"] = False
        ota_state["progress_percent"] = 100
        ota_state["description"] = f"Aggiornamento da file completato! ({files_copied} elementi copiati)"
        _ota_log("OTA da file completato con successo!")
        bus.emit_notification("Aggiornamento da file completato! ✅ Riavvia per applicare.", "success")
        log_event("ota", "info", "OTA da file: apply completato con successo", {
            "filename": staged_filename, "files_copied": files_copied, "backup": backup_name,
        })

    except Exception as e:
        ota_state["status"] = "failed"
        ota_state["running"] = False
        ota_state["error"] = str(e)
        ota_state["last_error"] = str(e)
        ota_state["description"] = f"Errore: {e}"
        _ota_log(f"ERRORE OTA da file: {e}")
        bus.emit_notification(f"Errore aggiornamento da file: {e}", "error")
        log_event("ota", "error", f"OTA da file: fallito — {e}", {
            "filename": staged_filename, "error": str(e),
        })
    finally:
        ota_state["finished_at"] = datetime.now().isoformat()
        _save_ota_state(ota_state)


@system_bp.route("/system/ota/upload", methods=["POST"])
def api_ota_upload():
    """
    Upload a package file to the OTA staging area.

    Accepts multipart/form-data with a ``file`` field.
    Allowed formats: .zip, .tar.gz
    Max size: OTA_MAX_PACKAGE_BYTES (100 MB).

    Returns the staged filename and updates ota_state to ``uploaded``.
    """
    if "file" not in request.files:
        return jsonify({"error": "Campo 'file' mancante nella richiesta"}), 400

    f = request.files["file"]
    original_name = f.filename or ""
    if not original_name:
        return jsonify({"error": "Nome file non valido"}), 400

    ext = _ota_package_extension(original_name)
    if ext is None:
        log_event("ota", "warning", "OTA upload rifiutato: estensione non consentita", {"filename": original_name})
        return jsonify({
            "error": (
                f"Estensione non consentita: '{original_name}'. "
                "Usa .zip o .tar.gz"
            )
        }), 400

    content_length = request.content_length or 0
    if content_length > OTA_MAX_PACKAGE_BYTES:
        log_event("ota", "warning", "OTA upload rifiutato: file troppo grande", {
            "filename": original_name, "max_bytes": OTA_MAX_PACKAGE_BYTES,
        })
        return jsonify({
            "error": (
                f"File troppo grande (max {OTA_MAX_PACKAGE_BYTES // (1024*1024)} MB). "
                f"Dimensione ricevuta: > {OTA_MAX_PACKAGE_BYTES // (1024*1024)} MB"
            )
        }), 413

    # Save to staging dir in streaming mode (fixed name, sanitised)
    staged_name = "staged_package" + ext
    staged_path = os.path.join(OTA_STAGING_DIR, staged_name)
    size_bytes = 0
    try:
        with open(staged_path, "wb") as out:
            while True:
                chunk = f.stream.read(OTA_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > OTA_MAX_PACKAGE_BYTES:
                    raise ValueError("too_large")
                out.write(chunk)
    except ValueError as e:
        if str(e) == "too_large":
            try:
                os.remove(staged_path)
            except OSError:
                pass
            log_event("ota", "warning", "OTA upload rifiutato: file troppo grande", {
                "filename": original_name, "max_bytes": OTA_MAX_PACKAGE_BYTES,
            })
            return jsonify({
                "error": (
                    f"File troppo grande (max {OTA_MAX_PACKAGE_BYTES // (1024*1024)} MB). "
                    f"Dimensione ricevuta: > {OTA_MAX_PACKAGE_BYTES // (1024*1024)} MB"
                )
            }), 413
    except Exception as e:
        log(f"Errore salvataggio package OTA: {e}", "warning")
        return jsonify({"error": "Impossibile salvare il package nella staging area"}), 500

    # Update ota_state
    ota_state = _load_ota_state()
    ota_state.update({
        "status": "uploaded",
        "running": False,
        "mode": "file",
        "staged_filename": original_name,
        "staged_at": datetime.now().isoformat(),
        "error": None,
        "description": f"Package '{original_name}' caricato, pronto per la validazione.",
    })
    _save_ota_state(ota_state)
    _ota_log(f"Package OTA caricato: {original_name} ({size_bytes} bytes) → {staged_name}")
    log_event("ota", "info", f"Package OTA caricato: {original_name}", {
        "filename": original_name, "size_bytes": size_bytes, "ext": ext,
    })

    return jsonify({
        "status": "uploaded",
        "filename": original_name,
        "size_bytes": size_bytes,
        "ext": ext,
    })


@system_bp.route("/system/ota/apply_uploaded", methods=["POST"])
def api_ota_apply_uploaded():
    """
    Validate and apply the previously uploaded package.

    This endpoint is async: the apply runs in a background thread.
    Requires a previously uploaded package (ota_state.status == 'uploaded').
    """
    if not _ota_lock.acquire(blocking=False):
        return jsonify({"error": "Un aggiornamento è già in corso"}), 409

    # Find the staged file
    ota_state = _load_ota_state()
    staged_filename = ota_state.get("staged_filename") or ""
    ext = _ota_package_extension(staged_filename)
    if not ext:
        _ota_lock.release()
        return jsonify({"error": "Nessun package caricato o estensione non riconosciuta"}), 400

    staged_name = "staged_package" + ext
    staged_path = os.path.join(OTA_STAGING_DIR, staged_name)
    if not os.path.isfile(staged_path):
        _ota_lock.release()
        return jsonify({"error": "Package non trovato nella staging area. Caricalo di nuovo."}), 404

    def _worker():
        try:
            _run_ota_file(staged_path, staged_filename, ext)
        finally:
            _ota_lock.release()

    t_ota = threading.Thread(target=_worker, daemon=True)
    t_ota.start()
    bus.emit_notification(f"Apply OTA da file avviato: {staged_filename} ⬆️", "info")
    return jsonify({"status": "started", "filename": staged_filename})


# =========================================================
# STANDBY — Stato e controllo
# =========================================================

@system_bp.route("/system/standby", methods=["GET"])
def api_standby_status():
    """Restituisce lo stato standby applicativo corrente."""
    return jsonify({
        "in_standby": is_in_standby(),
        "standby_state": get_standby_state(),
    })


# =========================================================
# DATA/ORA E TIMEZONE
# =========================================================

def _get_current_timezone():
    """Legge il timezone corrente del sistema."""
    try:
        import subprocess
        result = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=5
        )
        tz = result.stdout.strip()
        if tz:
            return tz
    except Exception:
        pass
    try:
        with open("/etc/timezone", "r") as f:
            return f.read().strip()
    except Exception:
        pass
    return "UTC"


def _get_ntp_status():
    """Restituisce lo stato del servizio NTP."""
    try:
        import subprocess
        result = subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=5
        )
        synced = result.stdout.strip().lower() in ("yes", "true", "1")
        return {"enabled": True, "synchronized": synced}
    except Exception:
        return {"enabled": False, "synchronized": False}


@system_bp.route("/system/datetime", methods=["GET"])
def api_datetime_status():
    """Restituisce data/ora corrente, timezone e stato NTP del dispositivo."""
    now = datetime.now()
    return jsonify({
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timestamp": int(now.timestamp()),
        "timezone": _get_current_timezone(),
        "ntp": _get_ntp_status(),
    })


@system_bp.route("/system/timezone", methods=["POST"])
def api_set_timezone():
    """Imposta il timezone di sistema (richiede sudo timedatectl)."""
    import re
    data = request.get_json(silent=True) or {}
    tz = str(data.get("timezone", "")).strip()
    if not tz:
        return jsonify({"error": "Campo 'timezone' obbligatorio"}), 400
    if not re.match(r'^[A-Za-z0-9_/+-]{1,64}$', tz):
        return jsonify({"error": "Timezone non valido"}), 400
    code, out, err = run_cmd(["sudo", "timedatectl", "set-timezone", tz])
    if code != 0:
        log(f"Errore impostazione timezone '{tz}': {err}", "warning")
        return jsonify({"error": "Impossibile impostare il timezone. Verificare che il timezone sia valido."}), 500
    log(f"Timezone impostato: {tz}", "info")
    log_event("system", "info", f"Timezone impostato: {tz}", {"timezone": tz})
    return jsonify({"status": "ok", "timezone": tz})


@system_bp.route("/system/ntp/sync", methods=["POST"])
def api_ntp_sync():
    """Forza sincronizzazione NTP."""
    code, out, err = run_cmd(["sudo", "timedatectl", "set-ntp", "true"])
    if code != 0:
        log(f"Errore abilitazione NTP: {err}", "warning")
        return jsonify({"error": "Impossibile abilitare NTP. Verificare i permessi sudo."}), 500
    # best-effort immediate sync via chronyc; log failure but don't block the response
    c_code, _, c_err = run_cmd(["sudo", "chronyc", "makestep"])
    if c_code != 0:
        log(f"chronyc makestep non disponibile: {c_err}", "info")
    return jsonify({"status": "ok", "message": "Sincronizzazione NTP avviata"})
