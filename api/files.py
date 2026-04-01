import os
import shutil
import mimetypes
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

# Importiamo le costanti e le utility di sicurezza
from config import FILE_MANAGER_ROOTS, FILE_MANAGER_DEFAULT_PATH, CHUNK_UPLOAD_ROOT
from core.utils import secure_open_read, log
from core.state import bus

# Creiamo il Blueprint
files_bp = Blueprint('files', __name__)

# =========================================================
# NAVIGAZIONE CARTELLE
# =========================================================
@files_bp.route("/files/default-root", methods=["GET"])
def api_files_default_root():
    """Restituisce la cartella di partenza e le radici consentite"""
    return jsonify({
        "default_path": FILE_MANAGER_DEFAULT_PATH,
        "allowed_roots": FILE_MANAGER_ROOTS
    })

@files_bp.route("/files/list", methods=["GET"])
def api_files_list():
    """Elenca i file e le cartelle (come 'ls') in modo sicuro"""
    req_path = request.args.get("path", "").strip() or FILE_MANAGER_DEFAULT_PATH
    req_path = os.path.realpath(req_path)
    
    # Controllo di sicurezza: siamo dentro una cartella consentita?
    if not any(req_path.startswith(os.path.realpath(r)) for r in FILE_MANAGER_ROOTS):
        return jsonify({"error": "Access Denied"}), 403

    if not os.path.isdir(req_path):
        return jsonify({"error": "Cartella non trovata"}), 404

    entries = []
    try:
        for item in os.listdir(req_path):
            full_path = os.path.join(req_path, item)
            is_dir = os.path.isdir(full_path)
            size = os.path.getsize(full_path) if not is_dir else 0
            
            # Identificazione sommaria del tipo per il frontend
            mime, _ = mimetypes.guess_type(full_path)
            f_type = "unknown"
            if mime:
                if mime.startswith("audio/"): f_type = "audio"
                elif mime.startswith("video/"): f_type = "video"
                elif mime.startswith("image/"): f_type = "image"
            
            entries.append({
                "name": item,
                "path": full_path,
                "is_dir": is_dir,
                "size": size,
                "type": f_type
            })
            
        # Ordina: prima le cartelle, poi i file in ordine alfabetico
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        
    except Exception as e:
        log(f"Errore lettura cartella {req_path}: {e}", "error")
        return jsonify({"error": "Impossibile leggere la cartella"}), 500

    return jsonify({
        "current_path": req_path,
        "entries": entries,
        "default_path": FILE_MANAGER_DEFAULT_PATH,
        "allowed_roots": FILE_MANAGER_ROOTS
    })

# =========================================================
# LETTURA FILE (Sicurezza TOCTOU)
# =========================================================
@files_bp.route("/files/open", methods=["GET"])
def api_files_open():
    """Restituisce un file binario (MP3, JPG) usando i File Descriptor sicuri"""
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "Percorso mancante"}), 400
        
    try:
        # Questa è la vera magia di sicurezza: se qualcuno ha piazzato un symlink
        # a /etc/passwd un attimo prima di questa chiamata, O_NOFOLLOW lo bloccherà!
        fd = secure_open_read(path, FILE_MANAGER_ROOTS)
        
        mime, _ = mimetypes.guess_type(path)
        return send_file(fd, mimetype=mime or "application/octet-stream")
    except ValueError as e:
        log(f"Tentativo di accesso illegale bloccato: {path}", "warning")
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": f"Errore apertura: {str(e)}"}), 500

# =========================================================
# OPERAZIONI DI BASE (Crea cartella, Elimina)
# =========================================================
@files_bp.route("/files/mkdir", methods=["POST"])
def api_files_mkdir():
    data = request.get_json(silent=True) or {}
    parent = data.get("path", "").strip()
    name = data.get("name", "").strip()
    
    if not parent or not name:
        return jsonify({"error": "Dati mancanti"}), 400
        
    # Validazione nome (evita attacchi di path traversal es. name="../../")
    name = secure_filename(name)
    new_dir = os.path.realpath(os.path.join(parent, name))
    
    if not any(new_dir.startswith(os.path.realpath(r)) for r in FILE_MANAGER_ROOTS):
        return jsonify({"error": "Access Denied"}), 403

    try:
        os.makedirs(new_dir, exist_ok=True)
        log(f"Creata nuova cartella: {new_dir}", "info")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@files_bp.route("/files/delete", methods=["POST"])
def api_files_delete():
    data = request.get_json(silent=True) or {}
    paths = data.get("paths", [])
    
    deleted_count = 0
    for p in paths:
        p_real = os.path.realpath(p)
        if not any(p_real.startswith(os.path.realpath(r)) for r in FILE_MANAGER_ROOTS):
            continue # Salta i path non autorizzati
            
        try:
            if os.path.isdir(p_real):
                shutil.rmtree(p_real)
            else:
                os.remove(p_real)
            deleted_count += 1
        except Exception as e:
            log(f"Impossibile eliminare {p_real}: {e}", "warning")
            
    bus.emit_notification(f"Eliminati {deleted_count} elementi", "info")
    return jsonify({"status": "ok", "deleted": deleted_count})

# NOTA: Per brevità ho omesso upload/chunk e zip/unzip, ma seguono la stessa 
# identica logica di controllo di 'FILE_MANAGER_ROOTS' usando os.path.realpath().

