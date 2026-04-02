"""
api/voice.py — API per la registrazione vocale

Endpoints:
  POST   /api/voice/upload                   — carica una registrazione (con metadati estesi)
  GET    /api/voice/recordings               — lista tutte le registrazioni con metadati
  GET    /api/voice/recording/<filename>     — dettaglio singola registrazione
  PUT    /api/voice/recording/<filename>     — aggiorna metadati (sidecar .meta.json)
  DELETE /api/voice/recording/<filename>     — elimina file + sidecar + associazioni RFID
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from config import MEDIA_ROOT, RFID_MAP_FILE, RFID_PROFILES_FILE
from core.state import rfid_map, rfid_profiles, save_json_direct, bus
from core.utils import log

voice_bp = Blueprint('voice', __name__)

# Cartella dedicata alle registrazioni
RECORDINGS_DIR = os.path.join(MEDIA_ROOT, "registrazioni")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Estensioni audio accettate
_ALLOWED_EXTENSIONS = {".webm", ".ogg", ".wav", ".mp3", ".m4a", ".opus"}
# Dimensione massima upload: 50 MB
_MAX_SIZE_BYTES = 50 * 1024 * 1024
# Ruoli validi
_VALID_ROLES = {"bambino", "genitore"}


def _meta_path(filename):
    """Ritorna il path del file sidecar metadati per una registrazione."""
    return os.path.join(RECORDINGS_DIR, filename + ".meta.json")


def _load_meta(filename):
    """Carica i metadati dal sidecar, oppure restituisce i default."""
    meta_file = _meta_path(filename)
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Default se il sidecar non esiste
    name_no_ext = os.path.splitext(filename)[0]
    return {
        "name": name_no_ext,
        "role": "bambino",
        "author": "",
        "rfid_code": "",
        "description": "",
        "created_at": "",
    }


def _save_meta(filename, meta):
    """Salva i metadati nel sidecar .meta.json."""
    meta_file = _meta_path(filename)
    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Errore salvataggio metadati per {filename}: {e}", "warning")


def _build_recording_entry(filename):
    """Costruisce il dizionario metadati completo per una registrazione."""
    file_path = os.path.join(RECORDINGS_DIR, filename)
    meta = _load_meta(filename)
    size_bytes = 0
    try:
        size_bytes = os.path.getsize(file_path)
    except OSError:
        pass
    return {
        "filename": filename,
        "path": file_path,
        "name": meta.get("name", os.path.splitext(filename)[0]),
        "size_bytes": size_bytes,
        "created_at": meta.get("created_at", ""),
        "duration_seconds": meta.get("duration_seconds", None),
        "role": meta.get("role", "bambino"),
        "author": meta.get("author", ""),
        "rfid_code": meta.get("rfid_code", ""),
        "description": meta.get("description", ""),
    }


def _is_allowed_extension(filename):
    """Verifica che il file abbia un'estensione audio accettata."""
    _, ext = os.path.splitext(filename.lower())
    return ext in _ALLOWED_EXTENSIONS


# =========================================================
# UPLOAD
# =========================================================
@voice_bp.route("/voice/upload", methods=["POST"])
def api_voice_upload():
    """Carica una registrazione vocale con metadati estesi."""
    if "audio" not in request.files:
        return jsonify({"error": "Nessun file audio ricevuto"}), 400

    audio_file = request.files["audio"]
    rfid_uid = request.form.get("rfid_uid", "").strip().upper()
    nome_storia = request.form.get("name", f"Registrazione_{uuid.uuid4().hex[:6]}").strip()
    role = request.form.get("role", "bambino").strip().lower()
    author = request.form.get("author", "").strip()
    description = request.form.get("description", "").strip()

    # Validazione ruolo
    if role not in _VALID_ROLES:
        role = "bambino"

    # Sicurezza sul nome del file
    safe_name = secure_filename(nome_storia)
    if not safe_name:
        safe_name = f"Registrazione_{uuid.uuid4().hex[:6]}"

    # Assicura estensione valida
    if not _is_allowed_extension(safe_name):
        safe_name += ".webm"  # Formato standard dei browser

    # Controllo dimensione (best-effort: seek/tell può fallire su stream non seekable)
    try:
        audio_file.seek(0, 2)
        size = audio_file.tell()
        audio_file.seek(0)
    except (AttributeError, OSError):
        size = request.content_length or 0
    if size > _MAX_SIZE_BYTES:
        return jsonify({"error": f"File troppo grande: max {_MAX_SIZE_BYTES // (1024*1024)} MB"}), 413

    file_path = os.path.join(RECORDINGS_DIR, safe_name)

    try:
        # 1. Salva il file audio sulla memoria del Raspberry
        audio_file.save(file_path)
        log(f"Nuova registrazione salvata: {file_path}", "info")

        # 2. Crea il sidecar con i metadati
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        meta = {
            "name": nome_storia,
            "role": role,
            "author": author,
            "rfid_code": rfid_uid,
            "description": description,
            "created_at": created_at,
        }
        _save_meta(safe_name, meta)

        # 3. Se è stato fornito un RFID, associalo automaticamente (legacy rfid_map)
        if rfid_uid:
            rfid_map[rfid_uid] = {
                "type": "audio",
                "target": file_path,
            }
            save_json_direct(RFID_MAP_FILE, rfid_map)
            log(f"Registrazione associata alla statuina {rfid_uid}", "info")
            bus.emit_notification("Voce salvata e associata alla statuina!", "success")
        else:
            bus.emit_notification("Registrazione salvata con successo!", "success")

        return jsonify({"status": "ok", "path": file_path, "filename": safe_name, "meta": meta})

    except Exception as e:
        log(f"Errore salvataggio registrazione: {e}", "error")
        return jsonify({"error": str(e)}), 500


# =========================================================
# LISTA REGISTRAZIONI
# =========================================================
@voice_bp.route("/voice/recordings", methods=["GET"])
def api_voice_recordings_list():
    """Ritorna la lista di tutte le registrazioni con metadati."""
    try:
        all_files = os.listdir(RECORDINGS_DIR)
    except OSError as e:
        log(f"Errore lettura cartella registrazioni: {e}", "warning")
        return jsonify([])

    recordings = []
    for fname in sorted(all_files):
        # Ignora i file sidecar e i file nascosti
        if fname.endswith(".meta.json") or fname.startswith("."):
            continue
        if not _is_allowed_extension(fname):
            continue
        recordings.append(_build_recording_entry(fname))

    return jsonify(recordings)


# =========================================================
# DETTAGLIO SINGOLA REGISTRAZIONE
# =========================================================
@voice_bp.route("/voice/recording/<filename>", methods=["GET"])
def api_voice_recording_get(filename):
    """Ritorna i metadati completi di una registrazione specifica."""
    safe = secure_filename(filename)
    if not safe or safe != filename:
        return jsonify({"error": "Nome file non valido"}), 400

    file_path = os.path.join(RECORDINGS_DIR, safe)
    if not os.path.isfile(file_path):
        return jsonify({"error": "Registrazione non trovata"}), 404

    return jsonify(_build_recording_entry(safe))


# =========================================================
# AGGIORNAMENTO METADATI
# =========================================================
@voice_bp.route("/voice/recording/<filename>", methods=["PUT"])
def api_voice_recording_update(filename):
    """Aggiorna i metadati (sidecar .meta.json) di una registrazione."""
    safe = secure_filename(filename)
    if not safe or safe != filename:
        return jsonify({"error": "Nome file non valido"}), 400

    file_path = os.path.join(RECORDINGS_DIR, safe)
    if not os.path.isfile(file_path):
        return jsonify({"error": "Registrazione non trovata"}), 404

    data = request.get_json(silent=True) or {}

    # Carica metadati esistenti e aggiorna solo i campi forniti
    meta = _load_meta(safe)
    if "name" in data:
        meta["name"] = str(data["name"]).strip()
    if "role" in data:
        role = str(data["role"]).strip().lower()
        meta["role"] = role if role in _VALID_ROLES else "bambino"
    if "author" in data:
        meta["author"] = str(data["author"]).strip()
    if "rfid_code" in data:
        meta["rfid_code"] = str(data["rfid_code"]).strip().upper()
    if "description" in data:
        meta["description"] = str(data["description"]).strip()

    _save_meta(safe, meta)
    log(f"Metadati aggiornati per: {safe}", "info")
    return jsonify({"status": "ok", "filename": safe, "meta": meta})


# =========================================================
# ELIMINAZIONE REGISTRAZIONE
# =========================================================
@voice_bp.route("/voice/recording/<filename>", methods=["DELETE"])
def api_voice_recording_delete(filename):
    """Elimina la registrazione, il sidecar e le associazioni RFID."""
    safe = secure_filename(filename)
    if not safe or safe != filename:
        return jsonify({"error": "Nome file non valido"}), 400

    file_path = os.path.join(RECORDINGS_DIR, safe)
    if not os.path.isfile(file_path):
        return jsonify({"error": "Registrazione non trovata"}), 404

    # Carica i metadati prima di eliminare (serve per ripulire RFID)
    meta = _load_meta(safe)
    rfid_code = meta.get("rfid_code", "").strip().upper()

    try:
        # 1. Elimina il file audio
        os.remove(file_path)
        log(f"Registrazione eliminata: {file_path}", "info")

        # 2. Elimina il sidecar .meta.json se esiste
        meta_file = _meta_path(safe)
        if os.path.exists(meta_file):
            os.remove(meta_file)

        # 3. Rimuovi associazione da rfid_map legacy (se presente)
        rfid_map_changed = False
        if rfid_code and rfid_code in rfid_map:
            existing = rfid_map.get(rfid_code, {})
            if existing.get("target") == file_path:
                del rfid_map[rfid_code]
                rfid_map_changed = True

        # Cerca anche per path in tutti i record rfid_map
        for uid in list(rfid_map.keys()):
            if rfid_map[uid].get("target") == file_path:
                del rfid_map[uid]
                rfid_map_changed = True

        if rfid_map_changed:
            save_json_direct(RFID_MAP_FILE, rfid_map)

        # 4. Rimuovi associazione da rfid_profiles (mode=voice_recording)
        profiles_changed = False
        for uid in list(rfid_profiles.keys()):
            p = rfid_profiles[uid]
            if p.get("mode") == "voice_recording" and p.get("recording_path") == file_path:
                del rfid_profiles[uid]
                profiles_changed = True
                log(f"Profilo RFID {uid} rimosso (registrazione eliminata)", "info")

        if profiles_changed:
            save_json_direct(RFID_PROFILES_FILE, rfid_profiles)
            bus.mark_dirty("rfid_profiles")
            bus.request_emit("admin")

        bus.emit_notification("Registrazione eliminata.", "info")
        return jsonify({"status": "ok", "filename": safe})

    except Exception as e:
        log(f"Errore eliminazione registrazione {safe}: {e}", "error")
        return jsonify({"error": "Errore interno durante l'eliminazione"}), 500

