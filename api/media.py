from flask import Blueprint, request, jsonify

# Importiamo lo stato globale, il bus degli eventi e le utility
from core.state import media_runtime, rfid_map, led_runtime, bus, save_json_direct
from config import RFID_MAP_FILE
from core.utils import log, run_cmd

# Importiamo il motore audio
from core.media import start_player, stop_player, send_mpv_command

# Creiamo il Blueprint
media_bp = Blueprint('media', __name__)

# =========================================================
# CONTROLLO RIPRODUZIONE (Play / Stop / Next / Prev)
# =========================================================
@media_bp.route("/media/play", methods=["POST"])
def api_media_play():
    data = request.get_json(silent=True) or {}
    target = data.get("target")
    mode = data.get("mode", "audio_only") # Può essere 'audio_only' o 'video_hdmi'
    rfid_uid = data.get("rfid_uid") # Opzionale, per forzare il resume da web
    
    if not target:
        return jsonify({"error": "Target mancante"}), 400
        
    log(f"Richiesta riproduzione manuale da API: {target}", "info")
    
    # Chiama la funzione sicura del core che stoppa il vecchio e avvia il nuovo
    success, msg = start_player(target, mode=mode, rfid_uid=rfid_uid)
    
    if success:
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": msg}), 500

@media_bp.route("/media/stop", methods=["POST"])
def api_media_stop():
    log("Richiesta stop da API", "info")
    stop_player()
    return jsonify({"status": "ok"})

@media_bp.route("/media/next", methods=["POST"])
def api_media_next():
    """Chiamata dai pulsanti fisici per la traccia successiva"""
    log("Comando NEXT ricevuto", "info")
    response = send_mpv_command(["playlist-next"])
    if response is None:
        return jsonify({"error": "Player non attivo o socket IPC non disponibile"}), 500
    return jsonify({"status": "ok"})

@media_bp.route("/media/prev", methods=["POST"])
def api_media_prev():
    """Chiamata dai pulsanti fisici per la traccia precedente"""
    log("Comando PREV ricevuto", "info")
    response = send_mpv_command(["playlist-prev"])
    if response is None:
        return jsonify({"error": "Player non attivo o socket IPC non disponibile"}), 500
    return jsonify({"status": "ok"})

@media_bp.route("/media/toggle_pause", methods=["POST"])
def api_media_toggle_pause():
    """
    Alterna pausa / ripresa sulla riproduzione in corso.
    Usa il comando MPV IPC 'cycle pause' per un toggle reale.
    """
    log("Comando TOGGLE_PAUSE ricevuto", "info")
    if not media_runtime.get("player_running"):
        return jsonify({"error": "Nessuna riproduzione in corso"}), 400
    response = send_mpv_command(["cycle", "pause"])
    if response is None:
        return jsonify({"error": "Player non attivo o socket IPC non disponibile"}), 500
    return jsonify({"status": "ok"})

# =========================================================
# CONTROLLO VOLUME
# =========================================================
@media_bp.route("/volume", methods=["GET", "POST"])
def api_volume():
    if request.method == "GET":
        return jsonify({"volume": media_runtime.get("current_volume", 60)})

    data = request.get_json(silent=True) or {}
    new_vol = data.get("volume")
    
    if new_vol is None:
        return jsonify({"error": "Volume mancante"}), 400
        
    try:
        new_vol = int(new_vol)
        # Limita il volume tra 0 e 100
        new_vol = max(0, min(100, new_vol))
        
        # Rispetta il Parental Control (se il volume massimo è bloccato a 80, non superarlo)
        from core.state import state
        max_allowed = state.get("parental_control", {}).get("max_volume", 100)
        if new_vol > max_allowed:
            new_vol = max_allowed
            
    except ValueError:
        return jsonify({"error": "Valore non valido"}), 400

    # 1. Aggiorna il volume di sistema di Linux (ALSA)
    run_cmd(["amixer", "sset", "Master", f"{new_vol}%"])
    
    # 2. Aggiorna lo stato in RAM
    media_runtime["current_volume"] = new_vol
    
    # 3. Avvisa l'EventBus di aggiornare il frontend
    bus.mark_dirty("media")
    bus.request_emit("public")
    
    return jsonify({"status": "ok", "volume": new_vol})

# =========================================================
# GESTIONE STATUINE MAGICHE (RFID) - CRUD
# =========================================================
@media_bp.route("/rfid/map", methods=["GET", "POST"])
def api_rfid_map():
    if request.method == "GET":
        # Ritorna tutte le associazioni correnti
        return jsonify(rfid_map)
        
    if request.method == "POST":
        # Crea o aggiorna un profilo statuina avanzato
        data = request.get_json(silent=True) or {}
        uid = data.get("uid", "").strip().upper()
        action_type = data.get("type", "audio")
        target = data.get("target", "").strip()
        
        if not uid or not target:
            return jsonify({"error": "Dati incompleti"}), 400

        # Costruisce il profilo (retrocompatibile con il formato semplice)
        profile = {
            "type": action_type,
            "target": target,
        }

        # Campi opzionali avanzati
        if "name" in data:
            profile["name"] = str(data["name"])
        if "mode" in data:
            profile["mode"] = str(data["mode"])
        if "folder" in data:
            profile["folder"] = str(data["folder"])
        if "webradio_url" in data:
            profile["webradio_url"] = str(data["webradio_url"])
        if "ai_prompt" in data:
            profile["ai_prompt"] = str(data["ai_prompt"])
        if "rss_url" in data:
            profile["rss_url"] = str(data["rss_url"])

        # Blocco LED opzionale
        led_data = data.get("led")
        if isinstance(led_data, dict):
            profile["led"] = {
                "enabled": bool(led_data.get("enabled", False)),
                "effect_id": str(led_data.get("effect_id", "solid")),
                "color": str(led_data.get("color", "#ffffff")),
                "brightness": int(led_data.get("brightness", 70)),
                "speed": int(led_data.get("speed", 30)),
                "params": led_data.get("params", {}),
            }
            
        # Aggiorna in RAM
        rfid_map[uid] = profile
        
        # Le statuine cambiano raramente, salviamo direttamente su SD
        save_json_direct(RFID_MAP_FILE, rfid_map)
        log(f"RFID {uid} associato a {action_type} -> {target}", "info")
        
        return jsonify({"status": "ok", "uid": uid})

@media_bp.route("/rfid/delete", methods=["POST"])
def api_rfid_delete():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid", "").strip().upper()
    
    if uid in rfid_map:
        del rfid_map[uid]
        save_json_direct(RFID_MAP_FILE, rfid_map)
        log(f"Associazione RFID {uid} eliminata", "info")
        # If the deleted profile was the active LED source, reset it
        if led_runtime.get("current_rfid") == uid:
            led_runtime["current_rfid"] = None
            _refresh_led_from_rfid()
        return jsonify({"status": "ok"})
        
    return jsonify({"error": "UID non trovato"}), 404

# =========================================================
# LED HELPER — chiamato dal trigger RFID
# =========================================================
def _refresh_led_from_rfid():
    """Aggiorna il runtime LED dopo un cambio di profilo RFID attivo."""
    try:
        from api.led import refresh_effective_led
        refresh_effective_led()
    except Exception as e:
        log(f"Errore refresh LED da RFID: {e}", "warning")


# =========================================================
# TRIGGER FISICO DELLA STATUINA (Dal lettore hardware)
# =========================================================
@media_bp.route("/rfid/trigger", methods=["POST"])
def api_rfid_trigger():
    """Questa rotta viene chiamata dallo script hw_rfid.py quando il sensore rileva una statuina"""
    data = request.get_json(silent=True) or {}
    uid = data.get("rfid_code", "").strip().upper()
    
    if not uid: 
        return jsonify({"error": "UID mancante"}), 400
        
    associazione = rfid_map.get(uid)
    
    if not associazione:
        log(f"Statuina {uid} appoggiata ma non riconosciuta nel database!", "warning")
        bus.emit_notification("Statuina sconosciuta! Associala dal pannello.", "warning")
        return jsonify({"error": "Statuina non associata", "uid": uid}), 404
        
    target = associazione.get("target")

    # Update LED runtime with RFID profile
    led_runtime["current_rfid"] = uid
    _refresh_led_from_rfid()
    
    # 🔀 BIVIO: È un link Web (YouTube/Radio/Podcast) o un file MP3 locale?
    if target.startswith("http://") or target.startswith("https://"):
        log(f"Avvio streaming Web/Podcast: {target}", "info")
        # Passiamo il link direttamente a MPV. Se è YouTube, yt-dlp estrarrà l'audio.
        # Passiamo anche l'UID per lo Smart Resume (anche sui podcast lunghi funziona!)
        start_player(target, mode="audio_only", rfid_uid=uid)
        bus.emit_notification("Streaming Web avviato! 🌍", "success")
        
    else:
        # È un file MP3 normale sulla scheda SD
        log(f"Avvio file locale: {target}", "info")
        start_player(target, mode="audio_only", rfid_uid=uid)
        bus.emit_notification("Riproduzione avviata! 🎵", "success")
    
    return jsonify({"status": "ok", "playing": target})

