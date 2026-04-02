"""
api/rfid.py — Profili RFID completi (PR 2 — Media / RFID)

Endpoints:
  GET    /api/rfid/profiles              — lista profili
  POST   /api/rfid/profile               — crea profilo
  PUT    /api/rfid/profile/<rfid_code>   — aggiorna profilo
  DELETE /api/rfid/profile/<rfid_code>   — elimina profilo
  GET    /api/rfid/current               — profilo / stato corrente
  POST   /api/rfid/trigger               — trigger manuale/hardware

Mantiene anche la rotta legacy /rfid/map (in api/media.py) per retrocompatibilità.

PR 21: aggiunto mode=edu_ai per collegare profili RFID a configurazioni AI educative.
"""
import re
import time
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify

from core.state import rfid_profiles, media_runtime, rss_runtime, bus, save_json_direct
from config import RFID_PROFILES_FILE
from core.utils import log
from core.event_log import log_event

rfid_bp = Blueprint("rfid", __name__)

# =========================================================
# VALIDAZIONE
# =========================================================
VALID_MODES = {"media_folder", "webradio", "ai_chat", "rss_feed", "edu_ai"}

# Educational AI constants (mirrors api/ai.py — kept in sync)
_VALID_AGE_GROUPS = {"bambino", "ragazzo", "adulto"}
_VALID_ACTIVITY_MODES = {
    "teaching_general", "quiz", "math", "animal_sounds_games",
    "interactive_story", "foreign_languages", "free_conversation",
}
_VALID_LANGUAGE_TARGETS = {"english", "spanish", "german", "french"}
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3,8}$')


def _is_valid_http_url(url):
    """Verifica che la stringa sia un URL HTTP/HTTPS valido con host."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _validate_edu_config_block(edu_config, update=False):
    """
    Valida il blocco edu_config di un profilo RFID.
    Ritorna (edu_dict, error_string).

    Campi:
      age_group       — bambino | ragazzo | adulto
      activity_mode   — modalità educativa AI
      language_target — solo per foreign_languages: english|spanish|german|french
      learning_step   — intero >= 1

    La lista `activities` (futura estensione multi-attività) è accettata se presente
    ma non validata in profondità: viene salvata così com'è per compatibilità futura.
    """
    if edu_config is None:
        return None, None
    if not isinstance(edu_config, dict):
        return None, "Il campo 'edu_config' deve essere un oggetto"

    errors = []

    age_group = str(edu_config.get("age_group", "bambino")).strip()
    if age_group not in _VALID_AGE_GROUPS:
        errors.append(f"edu_config.age_group non valido: '{age_group}'. Valori: {sorted(_VALID_AGE_GROUPS)}")
        age_group = "bambino"

    activity_mode = str(edu_config.get("activity_mode", "free_conversation")).strip()
    if activity_mode not in _VALID_ACTIVITY_MODES:
        errors.append(f"edu_config.activity_mode non valido: '{activity_mode}'. Valori: {sorted(_VALID_ACTIVITY_MODES)}")
        activity_mode = "free_conversation"

    language_target = str(edu_config.get("language_target", "english")).strip()
    if activity_mode == "foreign_languages" and language_target not in _VALID_LANGUAGE_TARGETS:
        errors.append(f"edu_config.language_target non valido: '{language_target}'. Valori: {sorted(_VALID_LANGUAGE_TARGETS)}")
        language_target = "english"

    learning_step = 1
    try:
        learning_step = max(1, int(edu_config.get("learning_step", 1)))
    except (TypeError, ValueError):
        errors.append("edu_config.learning_step deve essere un intero >= 1")

    if errors:
        return None, "; ".join(errors)

    result = {
        "age_group": age_group,
        "activity_mode": activity_mode,
        "language_target": language_target,
        "learning_step": learning_step,
    }

    # Preserve 'activities' list if provided (future multi-activity support)
    if isinstance(edu_config.get("activities"), list):
        result["activities"] = edu_config["activities"]

    return result, None


def _validate_led_block(led):
    """Valida il blocco LED opzionale. Ritorna (led_dict, error_string)."""
    if led is None:
        return None, None
    if not isinstance(led, dict):
        return None, "Il campo 'led' deve essere un oggetto"
    result = {
        "enabled": bool(led.get("enabled", False)),
        "effect_id": str(led.get("effect_id", "solid"))[:64],
        "color": str(led.get("color", "#ffffff")),
        "brightness": 70,
        "speed": 30,
        "params": {},
    }
    # Colore
    if not _HEX_COLOR_RE.match(result["color"]):
        result["color"] = "#ffffff"
    # Brightness
    try:
        b = int(led.get("brightness", 70))
        result["brightness"] = max(0, min(100, b))
    except (TypeError, ValueError):
        pass
    # Speed
    try:
        s = int(led.get("speed", 30))
        result["speed"] = max(0, min(100, s))
    except (TypeError, ValueError):
        pass
    # Params
    if isinstance(led.get("params"), dict):
        result["params"] = led["params"]
    return result, None


def validate_rfid_profile(data, update=False):
    """
    Valida i dati di un profilo RFID.
    update=True: i campi obbligatori possono mancare (PATCH semantics).
    Ritorna (profile_dict, error_string).
    """
    errors = []

    # rfid_code
    rfid_code = str(data.get("rfid_code", "")).strip().upper()
    if not update and not rfid_code:
        errors.append("rfid_code è obbligatorio")

    # name
    name = str(data.get("name", "")).strip()
    if not update and not name:
        errors.append("name è obbligatorio")

    # enabled
    enabled = bool(data.get("enabled", True))

    # mode
    mode = str(data.get("mode", "media_folder")).strip().lower()
    if mode not in VALID_MODES:
        errors.append(f"mode deve essere uno tra: {', '.join(sorted(VALID_MODES))}")

    # image_path (opzionale, percorso libero)
    image_path = str(data.get("image_path", "")).strip()

    # folder (richiesto se mode == media_folder)
    folder = str(data.get("folder", "")).strip()
    if not update and mode == "media_folder" and not folder:
        errors.append("folder è obbligatorio per mode=media_folder")

    # webradio_url (richiesto se mode == webradio)
    webradio_url = str(data.get("webradio_url", "")).strip()
    if not update and mode == "webradio":
        if not webradio_url:
            errors.append("webradio_url è obbligatorio per mode=webradio")
        elif not _is_valid_http_url(webradio_url):
            errors.append("webradio_url deve essere un URL HTTP/HTTPS valido")
    elif webradio_url and not _is_valid_http_url(webradio_url):
        errors.append("webradio_url deve essere un URL HTTP/HTTPS valido")

    # ai_prompt (opzionale)
    ai_prompt = str(data.get("ai_prompt", "")).strip()

    # rss_url (richiesto se mode == rss_feed)
    rss_url = str(data.get("rss_url", "")).strip()
    if not update and mode == "rss_feed":
        if not rss_url:
            errors.append("rss_url è obbligatorio per mode=rss_feed")
        elif not _is_valid_http_url(rss_url):
            errors.append("rss_url deve essere un URL HTTP/HTTPS valido")
    elif rss_url and not _is_valid_http_url(rss_url):
        errors.append("rss_url deve essere un URL HTTP/HTTPS valido")

    # rss_limit
    rss_limit = 10
    try:
        rss_limit = max(1, min(100, int(data.get("rss_limit", 10))))
    except (TypeError, ValueError):
        errors.append("rss_limit deve essere un numero intero tra 1 e 100")

    # volume
    volume = 70
    try:
        volume = max(0, min(100, int(data.get("volume", 70))))
    except (TypeError, ValueError):
        errors.append("volume deve essere un numero intero tra 0 e 100")

    # loop
    loop = bool(data.get("loop", True))

    # led
    led, led_error = _validate_led_block(data.get("led"))
    if led_error:
        errors.append(led_error)

    # edu_config (richiesto se mode == edu_ai, opzionale altrimenti)
    edu_config_raw = data.get("edu_config")
    if mode == "edu_ai" and not update and edu_config_raw is None:
        edu_config_raw = {}
    edu_config, edu_error = _validate_edu_config_block(edu_config_raw)
    if edu_error:
        errors.append(edu_error)

    if errors:
        return None, "; ".join(errors)

    profile = {
        "rfid_code": rfid_code,
        "name": name,
        "enabled": enabled,
        "mode": mode,
        "image_path": image_path,
        "folder": folder,
        "webradio_url": webradio_url,
        "ai_prompt": ai_prompt,
        "rss_url": rss_url,
        "rss_limit": rss_limit,
        "volume": volume,
        "loop": loop,
        "led": led,
        "edu_config": edu_config,
        "updated_at": int(time.time()),
    }
    return profile, None


# =========================================================
# CRUD PROFILI
# =========================================================
@rfid_bp.route("/rfid/profiles", methods=["GET"])
def api_rfid_profiles_list():
    """Ritorna tutti i profili RFID."""
    return jsonify(list(rfid_profiles.values()))


@rfid_bp.route("/rfid/profile", methods=["POST"])
def api_rfid_profile_create():
    """Crea un nuovo profilo RFID."""
    data = request.get_json(silent=True) or {}
    profile, err = validate_rfid_profile(data)
    if err:
        return jsonify({"error": err}), 400

    rfid_code = profile["rfid_code"]
    if not rfid_code:
        return jsonify({"error": "rfid_code è obbligatorio"}), 400

    if rfid_code in rfid_profiles:
        return jsonify({"error": f"Profilo {rfid_code} esiste già. Usa PUT per aggiornarlo."}), 409

    profile["created_at"] = int(time.time())
    rfid_profiles[rfid_code] = profile
    save_json_direct(RFID_PROFILES_FILE, rfid_profiles)
    bus.mark_dirty("rfid_profiles")
    bus.request_emit("admin")
    log(f"Profilo RFID creato: {rfid_code} ({profile['mode']})", "info")
    return jsonify({"status": "ok", "profile": profile}), 201


@rfid_bp.route("/rfid/profile/<rfid_code>", methods=["PUT"])
def api_rfid_profile_update(rfid_code):
    """Aggiorna un profilo RFID esistente."""
    rfid_code = rfid_code.strip().upper()
    if rfid_code not in rfid_profiles:
        return jsonify({"error": f"Profilo {rfid_code} non trovato"}), 404

    data = request.get_json(silent=True) or {}
    # Fonde i dati esistenti con quelli nuovi per il PUT completo
    existing = rfid_profiles[rfid_code].copy()
    merged = {**existing, **data, "rfid_code": rfid_code}

    profile, err = validate_rfid_profile(merged, update=True)
    if err:
        return jsonify({"error": err}), 400

    # Preserva created_at originale
    profile["created_at"] = existing.get("created_at", int(time.time()))
    rfid_profiles[rfid_code] = profile
    save_json_direct(RFID_PROFILES_FILE, rfid_profiles)
    bus.mark_dirty("rfid_profiles")
    bus.request_emit("admin")
    log(f"Profilo RFID aggiornato: {rfid_code}", "info")
    return jsonify({"status": "ok", "profile": profile})


@rfid_bp.route("/rfid/profile/<rfid_code>", methods=["DELETE"])
def api_rfid_profile_delete(rfid_code):
    """Elimina un profilo RFID."""
    rfid_code = rfid_code.strip().upper()
    if rfid_code not in rfid_profiles:
        return jsonify({"error": f"Profilo {rfid_code} non trovato"}), 404

    del rfid_profiles[rfid_code]
    save_json_direct(RFID_PROFILES_FILE, rfid_profiles)
    bus.mark_dirty("rfid_profiles")
    bus.request_emit("admin")
    log(f"Profilo RFID eliminato: {rfid_code}", "info")
    return jsonify({"status": "ok"})


# =========================================================
# STATO CORRENTE
# =========================================================
@rfid_bp.route("/rfid/current", methods=["GET"])
def api_rfid_current():
    """Ritorna il profilo RFID e lo stato di riproduzione corrente."""
    current_code = media_runtime.get("current_rfid")
    profile = rfid_profiles.get(current_code) if current_code else None
    return jsonify({
        "current_rfid": current_code,
        "current_profile": profile,
        "current_profile_name": media_runtime.get("current_profile_name"),
        "current_mode": media_runtime.get("current_mode", "idle"),
        "current_media_path": media_runtime.get("current_media_path"),
        "current_playlist": media_runtime.get("current_playlist", []),
        "playlist_index": media_runtime.get("playlist_index", 0),
        "player_running": media_runtime.get("player_running", False),
        "volume": media_runtime.get("current_volume", 70),
        "rss_state": rss_runtime.get(current_code) if current_code else None,
    })


# =========================================================
# TRIGGER
# =========================================================
@rfid_bp.route("/rfid/trigger", methods=["POST"])
def api_rfid_trigger_profile():
    """
    Trigger avanzato: usa il modello profilo completo.
    Supporta mode: media_folder, webradio, ai_chat, rss_feed, edu_ai.
    """
    data = request.get_json(silent=True) or {}
    rfid_code = str(data.get("rfid_code", "")).strip().upper()

    if not rfid_code:
        return jsonify({"error": "rfid_code mancante"}), 400

    profile = rfid_profiles.get(rfid_code)
    if not profile:
        log(f"Profilo RFID {rfid_code} non trovato — provo legacy rfid_map", "info")
        # Fallback al legacy rfid_map per retrocompatibilità
        from core.state import rfid_map
        legacy = rfid_map.get(rfid_code)
        if legacy:
            return _handle_legacy_trigger(rfid_code, legacy)
        bus.emit_notification("Statuina sconosciuta! Associala dal pannello.", "warning")
        return jsonify({"error": "Profilo non trovato", "rfid_code": rfid_code}), 404

    if not profile.get("enabled", True):
        log(f"Profilo RFID {rfid_code} disabilitato", "info")
        return jsonify({"status": "disabled", "rfid_code": rfid_code})

    mode = profile.get("mode", "media_folder")
    log(f"Trigger RFID: {rfid_code} → mode={mode}", "info")

    # Applica LED del profilo
    _apply_profile_led(rfid_code, profile)

    if mode == "media_folder":
        return _trigger_media_folder(rfid_code, profile)
    elif mode == "webradio":
        return _trigger_webradio(rfid_code, profile)
    elif mode == "ai_chat":
        return _trigger_ai_chat(rfid_code, profile)
    elif mode == "rss_feed":
        return _trigger_rss_feed(rfid_code, profile)
    elif mode == "edu_ai":
        return _trigger_edu_ai(rfid_code, profile)
    else:
        return jsonify({"error": f"mode non supportato: {mode}"}), 400


# =========================================================
# HANDLER PER OGNI MODE
# =========================================================
def _trigger_media_folder(rfid_code, profile):
    """mode=media_folder: costruisce playlist, usa resume, avvia."""
    from core.media import start_player, build_playlist
    from core.database import get_resume_position

    folder = profile.get("folder", "")
    if not folder:
        return jsonify({"error": "folder non specificato nel profilo"}), 400

    playlist = build_playlist(folder)
    if not playlist:
        bus.emit_notification(f"Cartella vuota o non trovata: {folder}", "warning")
        return jsonify({"error": "Nessun file media trovato nella cartella", "folder": folder}), 404

    # Determina indice di partenza tramite resume
    playlist_index = 0
    resume = get_resume_position(rfid_code)
    target = playlist[0]
    if resume and resume.get("playlist_index", 0) < len(playlist):
        playlist_index = resume["playlist_index"]
        target = playlist[playlist_index]

    # Aggiorna il runtime con la playlist completa
    media_runtime["current_playlist"] = playlist

    success, msg = start_player(
        target,
        mode="audio_only",
        rfid_uid=rfid_code,
        playlist_index=playlist_index,
        profile_name=profile.get("name"),
        profile_mode="media_folder",
        volume=profile.get("volume"),
    )

    if not success:
        return jsonify({"error": msg}), 500

    bus.emit_notification(f"▶️ {profile.get('name', rfid_code)}", "success")
    return jsonify({
        "status": "ok",
        "mode": "media_folder",
        "playing": target,
        "playlist_index": playlist_index,
        "playlist_count": len(playlist),
    })


def _trigger_webradio(rfid_code, profile):
    """mode=webradio: avvia stream URL."""
    from core.media import start_player

    url = profile.get("webradio_url", "")
    if not url:
        return jsonify({"error": "webradio_url non specificato"}), 400

    success, msg = start_player(
        url,
        mode="audio_only",
        rfid_uid=rfid_code,
        profile_name=profile.get("name"),
        profile_mode="webradio",
        volume=profile.get("volume"),
    )

    if not success:
        return jsonify({"error": msg}), 500

    bus.emit_notification(f"📻 {profile.get('name', rfid_code)}", "success")
    return jsonify({"status": "ok", "mode": "webradio", "url": url})


def _trigger_ai_chat(rfid_code, profile):
    """mode=ai_chat: attiva modalità AI con prompt del profilo."""
    from core.state import ai_runtime

    ai_runtime["active_rfid"] = rfid_code
    ai_runtime["active_profile_name"] = profile.get("name", "")
    ai_runtime["extra_prompt"] = profile.get("ai_prompt", "")
    bus.mark_dirty("ai")
    bus.request_emit("public")
    bus.emit_notification(f"🦉 {profile.get('name', rfid_code)}", "success")

    # Aggiorna media_runtime per snapshot
    media_runtime["current_rfid"] = rfid_code
    media_runtime["current_profile_name"] = profile.get("name")
    media_runtime["current_mode"] = "ai_chat"
    bus.mark_dirty("media")
    bus.request_emit("public")

    log(f"AI Chat attivata per profilo: {profile.get('name')} | prompt: {profile.get('ai_prompt', '')[:60]}", "info")
    return jsonify({
        "status": "ok",
        "mode": "ai_chat",
        "profile_name": profile.get("name"),
        "ai_prompt": profile.get("ai_prompt", ""),
    })


def _trigger_rss_feed(rfid_code, profile):
    """mode=rss_feed: fetch feed RSS e salva stato runtime."""
    rss_url = profile.get("rss_url", "")
    rss_limit = profile.get("rss_limit", 10)

    if not rss_url:
        return jsonify({"error": "rss_url non specificato"}), 400

    items, err = _fetch_rss(rss_url, rss_limit)
    if err:
        log(f"Errore RSS per RFID {rfid_code}: {err}", "warning")
        bus.emit_notification("Errore durante il fetch RSS", "warning")
        return jsonify({"error": "Errore durante il fetch del feed RSS"}), 500

    rss_state = {
        "rfid_code": rfid_code,
        "profile_name": profile.get("name"),
        "rss_url": rss_url,
        "fetched_at": int(time.time()),
        "items": items,
    }
    rss_runtime[rfid_code] = rss_state
    bus.mark_dirty("rss")
    bus.request_emit("public")

    # Aggiorna media_runtime
    media_runtime["current_rfid"] = rfid_code
    media_runtime["current_profile_name"] = profile.get("name")
    media_runtime["current_mode"] = "rss_feed"
    media_runtime["rss_state"] = rss_state
    bus.mark_dirty("media")
    bus.request_emit("public")

    bus.emit_notification(f"📰 {profile.get('name', rfid_code)} — {len(items)} articoli", "success")
    return jsonify({"status": "ok", "mode": "rss_feed", "items": items})


def _trigger_edu_ai(rfid_code, profile):
    """
    mode=edu_ai: attiva la configurazione AI educativa dal profilo RFID.

    Applica age_group, activity_mode, language_target, learning_step a ai_settings
    tramite api.ai.apply_rfid_edu_config(), resetta la cronologia chat per evitare
    incoerenze di sessione, e aggiorna snapshot/runtime.
    """
    from core.state import ai_runtime

    edu_config = profile.get("edu_config")
    if not edu_config:
        log(f"Profilo RFID {rfid_code} edu_ai: edu_config mancante", "warning")
        log_event("rfid", "warning", "Profilo RFID edu_ai senza edu_config", {
            "rfid_code": rfid_code,
            "profile_name": profile.get("name"),
        })
        bus.emit_notification("Configurazione educativa mancante nel profilo.", "warning")
        return jsonify({"error": "edu_config mancante nel profilo edu_ai"}), 400

    # Apply to ai_settings via api.ai helper
    try:
        from api.ai import apply_rfid_edu_config
        apply_rfid_edu_config(edu_config)
    except Exception as e:
        log(f"Errore applicazione config educativa RFID {rfid_code}: {e}", "warning")
        log_event("rfid", "error", "Errore attivazione AI educativa via RFID", {
            "rfid_code": rfid_code,
            "error": str(e),
        })
        bus.emit_notification("Errore nell'attivazione AI educativa.", "error")
        return jsonify({"error": "Errore attivazione AI educativa"}), 500

    # Track in ai_runtime
    ai_runtime["active_rfid"] = rfid_code
    ai_runtime["active_profile_name"] = profile.get("name", "")
    ai_runtime["edu_rfid_active"] = True
    # Reset chat history to avoid session mismatches
    ai_runtime["history"] = []
    bus.mark_dirty("ai")
    bus.request_emit("public")

    # Update media_runtime snapshot
    media_runtime["current_rfid"] = rfid_code
    media_runtime["current_profile_name"] = profile.get("name")
    media_runtime["current_mode"] = "edu_ai"
    bus.mark_dirty("media")
    bus.request_emit("public")

    activity_mode = edu_config.get("activity_mode", "free_conversation")
    age_group = edu_config.get("age_group", "bambino")
    language_target = edu_config.get("language_target", "english")
    learning_step = edu_config.get("learning_step", 1)

    log_event("rfid", "info", "AI educativa attivata via RFID", {
        "rfid_code": rfid_code,
        "profile_name": profile.get("name"),
        "age_group": age_group,
        "activity_mode": activity_mode,
        "language_target": language_target,
        "learning_step": learning_step,
    })

    log(
        f"AI educativa attivata: RFID={rfid_code} profilo={profile.get('name')} "
        f"modalità={activity_mode} fascia={age_group}",
        "info",
    )
    bus.emit_notification(f"🎓 {profile.get('name', rfid_code)}", "success")

    return jsonify({
        "status": "ok",
        "mode": "edu_ai",
        "profile_name": profile.get("name"),
        "rfid_code": rfid_code,
        "edu_config": {
            "age_group": age_group,
            "activity_mode": activity_mode,
            "language_target": language_target,
            "learning_step": learning_step,
        },
    })


# =========================================================
# HELPERS
# =========================================================
def _fetch_rss(rss_url, limit=10):
    """Fetch e parse feed RSS tramite feedparser. Delega a api.rss per evitare duplicazioni."""
    from api.rss import _fetch_and_summarize
    return _fetch_and_summarize(rss_url, limit)


def _apply_profile_led(rfid_code, profile):
    """Applica il blocco LED del profilo al runtime LED."""
    led_block = profile.get("led")
    if not led_block or not led_block.get("enabled"):
        return
    try:
        from core.state import led_runtime
        led_runtime["current_effect"] = led_block.get("effect_id", "solid")
        led_runtime["master_color"] = led_block.get("color", "#ffffff")
        led_runtime["master_brightness"] = led_block.get("brightness", 70)
        led_runtime["master_speed"] = led_block.get("speed", 30)
        led_runtime["led_source"] = "rfid_profile"
        led_runtime["led_rfid_code"] = rfid_code
        bus.mark_dirty("led")
        bus.request_emit("public")
        log(f"LED profilo applicato per RFID {rfid_code}: {led_block.get('effect_id')}", "info")
    except Exception as e:
        log(f"Errore applicazione LED profilo: {e}", "warning")


def _handle_legacy_trigger(rfid_code, assoc):
    """Gestisce trigger per profili nel legacy rfid_map (retrocompatibilità)."""
    from core.media import start_player
    target = assoc.get("target", "")
    if not target:
        return jsonify({"error": "Target mancante nel profilo legacy"}), 400

    _apply_profile_led(rfid_code, assoc)

    start_player(target, mode="audio_only", rfid_uid=rfid_code,
                 profile_name=assoc.get("name"), profile_mode=assoc.get("mode"))
    bus.emit_notification(f"▶️ {assoc.get('name', rfid_code)}", "success")
    return jsonify({"status": "ok", "mode": "legacy", "playing": target})
