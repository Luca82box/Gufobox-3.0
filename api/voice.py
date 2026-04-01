import os
import uuid
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from config import MEDIA_ROOT, RFID_MAP_FILE
from core.state import rfid_map, save_json_direct, bus
from core.utils import log

voice_bp = Blueprint('voice', __name__)

# Creiamo la cartella dedicata alle registrazioni se non esiste
RECORDINGS_DIR = os.path.join(MEDIA_ROOT, "registrazioni")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

@voice_bp.route("/voice/upload", methods=["POST"])
def api_voice_upload():
    if "audio" not in request.files:
        return jsonify({"error": "Nessun file audio ricevuto"}), 400
        
    audio_file = request.files["audio"]
    rfid_uid = request.form.get("rfid_uid", "").strip().upper()
    nome_storia = request.form.get("name", f"Registrazione_{uuid.uuid4().hex[:6]}").strip()
    
    # Sicurezza sul nome del file
    safe_name = secure_filename(nome_storia)
    if not safe_name.endswith(".webm") and not safe_name.endswith(".ogg") and not safe_name.endswith(".wav"):
        safe_name += ".webm" # Formato standard dei browser
        
    file_path = os.path.join(RECORDINGS_DIR, safe_name)
    
    try:
        # 1. Salva il file audio sulla memoria del Raspberry
        audio_file.save(file_path)
        log(f"Nuova registrazione salvata: {file_path}", "info")
        
        # 2. Se è stato fornito un RFID, associalo automaticamente!
        if rfid_uid:
            rfid_map[rfid_uid] = {
                "type": "audio",
                "target": file_path
            }
            save_json_direct(RFID_MAP_FILE, rfid_map)
            log(f"Registrazione associata alla statuina {rfid_uid}", "info")
            bus.emit_notification(f"Voce salvata e associata alla statuina!", "success")
        else:
            bus.emit_notification("Registrazione salvata con successo!", "success")
            
        return jsonify({"status": "ok", "path": file_path})
        
    except Exception as e:
        log(f"Errore salvataggio registrazione: {e}", "error")
        return jsonify({"error": str(e)}), 500

