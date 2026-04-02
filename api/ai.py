import os
import hashlib
from flask import Blueprint, request, jsonify, send_file

# Importiamo la configurazione e lo stato
from config import AI_SETTINGS_FILE, AI_TTS_CACHE_DIR, OPENAI_API_KEY
from core.state import ai_runtime, led_runtime, bus, load_json, save_json_direct
from core.utils import log
from core.event_log import log_event

# Proviamo a importare OpenAI (se installato)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

ai_bp = Blueprint('ai', __name__)

# =========================================================
# EDUCATIONAL AI CONSTANTS
# =========================================================
VALID_AGE_GROUPS = {"bambino", "ragazzo", "adulto"}
VALID_ACTIVITY_MODES = {
    "teaching_general",
    "quiz",
    "math",
    "animal_sounds_games",
    "interactive_story",
    "foreign_languages",
    "free_conversation",
}
VALID_LANGUAGE_TARGETS = {"english", "spanish", "german", "french"}

# Maps legacy interactive_mode values -> canonical activity_mode
LEGACY_MODE_MAP = {
    "chat_normale":       "free_conversation",
    "storia_interattiva": "interactive_story",
    "quiz_animali":       "animal_sounds_games",
    "insegnante_lingue":  "foreign_languages",
    "indovinelli":        "quiz",
    "matematica":         "math",
}

# Maps legacy target_lang codes -> canonical language_target
LEGACY_LANG_MAP = {
    "en": "english",
    "es": "spanish",
    "de": "german",
    "fr": "french",
}

# Reverse: canonical language_target -> legacy code
LANG_TO_CODE = {v: k for k, v in LEGACY_LANG_MAP.items()}

# Italian display names for languages
LANGUAGE_NAMES_IT = {
    "english": "inglese",
    "spanish": "spagnolo",
    "german":  "tedesco",
    "french":  "francese",
}

# Activity mode display names (Italian)
ACTIVITY_MODE_LABELS = {
    "teaching_general":   "Insegnamento Generale",
    "quiz":               "Quiz",
    "math":               "Matematica",
    "animal_sounds_games":"Animali e Versi",
    "interactive_story":  "Storia Interattiva",
    "foreign_languages":  "Lingue Straniere",
    "free_conversation":  "Conversazione Libera",
}

# Carichiamo le impostazioni dell'AI (System prompt, voce, ecc.)
ai_settings = load_json(AI_SETTINGS_FILE, {
    "system_prompt": "Sei il Gufetto Magico, un assistente amichevole e saggio che parla ai bambini.",
    "temperature": 0.7,
    "tts_provider": "browser",
    "openai_api_key": OPENAI_API_KEY,
    # Educational AI settings
    "age_group": "bambino",
    "activity_mode": "free_conversation",
    "language_target": "english",
    "learning_step": 1,
    # Legacy aliases kept for backward compat
    "age_profile": "bambino",
    "interactive_mode": "chat_normale",
    "target_lang": "en",
})

# =========================================================
# EDUCATIONAL AI HELPERS
# =========================================================

def _get_edu_config():
    """Return canonical (age_group, activity_mode, language_target, learning_step).
    Reads new field names with fallback to legacy names for backward compat."""
    age_group = ai_settings.get("age_group") or ai_settings.get("age_profile", "bambino")
    if age_group not in VALID_AGE_GROUPS:
        age_group = "bambino"

    raw_mode = ai_settings.get("activity_mode") or ai_settings.get("interactive_mode", "free_conversation")
    activity_mode = LEGACY_MODE_MAP.get(raw_mode, raw_mode)
    if activity_mode not in VALID_ACTIVITY_MODES:
        activity_mode = "free_conversation"

    raw_lang = ai_settings.get("language_target") or ai_settings.get("target_lang", "english")
    language_target = LEGACY_LANG_MAP.get(raw_lang, raw_lang)
    if language_target not in VALID_LANGUAGE_TARGETS:
        language_target = "english"

    try:
        learning_step = max(1, int(ai_settings.get("learning_step", 1)))
    except (TypeError, ValueError):
        learning_step = 1

    return age_group, activity_mode, language_target, learning_step


def _validate_edu_config(age_group, activity_mode, language_target, learning_step):
    """Return list of error strings; empty list means config is valid."""
    errors = []
    if age_group not in VALID_AGE_GROUPS:
        errors.append(f"age_group non valido: '{age_group}'. Valori: {sorted(VALID_AGE_GROUPS)}")
    if activity_mode not in VALID_ACTIVITY_MODES:
        errors.append(f"activity_mode non valido: '{activity_mode}'. Valori: {sorted(VALID_ACTIVITY_MODES)}")
    if activity_mode == "foreign_languages" and language_target not in VALID_LANGUAGE_TARGETS:
        errors.append(f"language_target non valido: '{language_target}'. Valori: {sorted(VALID_LANGUAGE_TARGETS)}")
    if not isinstance(learning_step, int) or learning_step < 1:
        errors.append("learning_step deve essere un intero >= 1")
    return errors


def _sync_legacy_edu_fields():
    """Keep legacy field names in sync with canonical ones after a settings update."""
    age_group = ai_settings.get("age_group", "bambino")
    ai_settings["age_profile"] = age_group

    activity_mode = ai_settings.get("activity_mode", "free_conversation")
    # Store legacy mode name too (best-effort reverse map)
    reverse_mode = {v: k for k, v in LEGACY_MODE_MAP.items()}
    ai_settings["interactive_mode"] = reverse_mode.get(activity_mode, activity_mode)

    language_target = ai_settings.get("language_target", "english")
    ai_settings["target_lang"] = LANG_TO_CODE.get(language_target, language_target)


def apply_rfid_edu_config(edu_config: dict) -> None:
    """
    Apply an edu_config dict (from an RFID profile) to the live ai_settings.

    Called by api/rfid.py when a statuette with mode=edu_ai is triggered.
    Validates each field against the canonical sets and falls back to safe
    defaults rather than raising, so a partial/invalid config never crashes.

    Args:
        edu_config: dict with keys age_group, activity_mode, language_target,
                    learning_step.  Extra keys are silently ignored.
    """
    age_group = str(edu_config.get("age_group", "bambino")).strip()
    if age_group not in VALID_AGE_GROUPS:
        log_event("ai", "warning", "apply_rfid_edu_config: age_group non valido, uso bambino", {
            "received": age_group,
            "valid": sorted(VALID_AGE_GROUPS),
        })
        age_group = "bambino"

    activity_mode = str(edu_config.get("activity_mode", "free_conversation")).strip()
    if activity_mode not in VALID_ACTIVITY_MODES:
        log_event("ai", "warning", "apply_rfid_edu_config: activity_mode non valido, uso free_conversation", {
            "received": activity_mode,
            "valid": sorted(VALID_ACTIVITY_MODES),
        })
        activity_mode = "free_conversation"

    language_target = str(edu_config.get("language_target", "english")).strip()
    if language_target not in VALID_LANGUAGE_TARGETS:
        log_event("ai", "warning", "apply_rfid_edu_config: language_target non valido, uso english", {
            "received": language_target,
            "valid": sorted(VALID_LANGUAGE_TARGETS),
        })
        language_target = "english"

    try:
        learning_step = max(1, int(edu_config.get("learning_step", 1)))
    except (TypeError, ValueError):
        learning_step = 1

    ai_settings["age_group"] = age_group
    ai_settings["activity_mode"] = activity_mode
    ai_settings["language_target"] = language_target
    ai_settings["learning_step"] = learning_step
    _sync_legacy_edu_fields()

    save_json_direct(AI_SETTINGS_FILE, ai_settings)
    bus.mark_dirty("ai")
    bus.request_emit("public")


# =========================================================
# Canonical AI status values
AI_STATUS_IDLE = "idle"
AI_STATUS_LISTENING = "listening"
AI_STATUS_THINKING = "thinking"
AI_STATUS_SPEAKING = "speaking"
AI_STATUS_ERROR = "error"


def _set_ai_state(status: str, error: str = None):
    """
    Update the canonical AI status in ai_runtime and sync to LED runtime.

    status: "idle" | "listening" | "thinking" | "speaking" | "error"
    error:  optional error message (set when status == "error")
    """
    ai_runtime["status"] = status
    # Keep legacy boolean fields in sync for backward compat
    ai_runtime["is_thinking"] = status == AI_STATUS_THINKING
    ai_runtime["is_speaking"] = status == AI_STATUS_SPEAKING
    if status == AI_STATUS_ERROR and error:
        ai_runtime["last_error"] = error
    elif status == AI_STATUS_IDLE:
        ai_runtime["last_error"] = None
    # Sync to LED layer (None when idle so LED reverts to default)
    led_ai = status if status != AI_STATUS_IDLE else None
    try:
        from api.led import refresh_effective_led
        led_runtime["ai_state"] = led_ai
        refresh_effective_led()
    except Exception as e:
        log(f"Errore aggiornamento LED per stato AI '{status}': {e}", "warning")
    bus.mark_dirty("ai")
    bus.request_emit("public")


def get_openai_client():
    """Inizializza il client OpenAI usando la chiave salvata nelle impostazioni"""
    api_key = ai_settings.get("openai_api_key") or OPENAI_API_KEY
    if not api_key or not OpenAI:
        return None
    return OpenAI(api_key=api_key)

# =========================================================
# IMPOSTAZIONI AI (Per il pannello Admin)
# =========================================================
@ai_bp.route("/ai/settings", methods=["GET"])
def api_ai_settings_get():
    # Nascondiamo in parte la chiave API per sicurezza quando la inviamo al frontend
    safe_settings = ai_settings.copy()
    key = safe_settings.get("openai_api_key", "")
    if len(key) > 8:
        safe_settings["openai_api_key"] = key[:4] + "*" * (len(key)-8) + key[-4:]
    return jsonify(safe_settings)

@ai_bp.route("/ai/settings", methods=["POST"])
def api_ai_settings_post():
    data = request.get_json(silent=True) or {}
    
    # Aggiorniamo solo i campi inviati (se la chiave API contiene '*', significa che non è stata modificata)
    for k, v in data.items():
        if k == "openai_api_key" and "*" in str(v):
            continue
        ai_settings[k] = v

    # Normalize educational fields: accept both old and new names
    # If new names were sent, canonicalize them; always sync legacy aliases
    if "activity_mode" in data:
        raw = ai_settings.get("activity_mode", "free_conversation")
        ai_settings["activity_mode"] = LEGACY_MODE_MAP.get(raw, raw)
        if ai_settings["activity_mode"] not in VALID_ACTIVITY_MODES:
            ai_settings["activity_mode"] = "free_conversation"
    elif "interactive_mode" in data:
        raw = data["interactive_mode"]
        ai_settings["activity_mode"] = LEGACY_MODE_MAP.get(raw, raw)
        if ai_settings["activity_mode"] not in VALID_ACTIVITY_MODES:
            ai_settings["activity_mode"] = "free_conversation"

    if "language_target" in data:
        raw = ai_settings.get("language_target", "english")
        ai_settings["language_target"] = LEGACY_LANG_MAP.get(raw, raw)
        if ai_settings["language_target"] not in VALID_LANGUAGE_TARGETS:
            ai_settings["language_target"] = "english"
    elif "target_lang" in data:
        ai_settings["language_target"] = LEGACY_LANG_MAP.get(data["target_lang"], data["target_lang"])

    if "age_profile" in data and "age_group" not in data:
        ai_settings["age_group"] = data["age_profile"]

    if ai_settings.get("age_group") not in VALID_AGE_GROUPS:
        ai_settings["age_group"] = "bambino"

    try:
        ai_settings["learning_step"] = max(1, int(ai_settings.get("learning_step", 1)))
    except (TypeError, ValueError):
        ai_settings["learning_step"] = 1

    _sync_legacy_edu_fields()
    save_json_direct(AI_SETTINGS_FILE, ai_settings)
    log("Impostazioni AI aggiornate", "info")
    return jsonify({"status": "ok"})

# =========================================================
# STATUS AI
# =========================================================
@ai_bp.route("/ai/status", methods=["GET"])
def api_ai_status():
    """Return the current AI runtime status including educational config."""
    age_group, activity_mode, language_target, learning_step = _get_edu_config()
    return jsonify({
        "status": ai_runtime.get("status", AI_STATUS_IDLE),
        "last_error": ai_runtime.get("last_error"),
        "history_length": len(ai_runtime.get("history", [])),
        "tts_provider": ai_settings.get("tts_provider", "browser"),
        "openai_configured": bool(ai_settings.get("openai_api_key") or OPENAI_API_KEY),
        # Educational config
        "age_group": age_group,
        "activity_mode": activity_mode,
        "activity_mode_label": ACTIVITY_MODE_LABELS.get(activity_mode, activity_mode),
        "language_target": language_target,
        "learning_step": learning_step,
        # RFID source (set by edu_ai trigger)
        "active_rfid": ai_runtime.get("active_rfid"),
        "active_profile_name": ai_runtime.get("active_profile_name"),
        "edu_rfid_active": bool(ai_runtime.get("edu_rfid_active", False)),
    })

# =========================================================
# CHAT E CONVERSAZIONE
# =========================================================
@ai_bp.route("/ai/chat", methods=["POST"])
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    user_text = data.get("text", "").strip()
    
    if not user_text:
        return jsonify({"error": "Testo vuoto"}), 400

    client = get_openai_client()
    if not client:
        msg = "OpenAI non configurato. Inserisci la API Key nelle impostazioni."
        log_event("ai", "error", "AI chat fallita: OpenAI non configurato")
        return jsonify({"error": msg, "code": "openai_not_configured"}), 503

    # 1. Aggiungiamo il messaggio dell'utente alla storia con timestamp
    import time as _time
    ai_runtime["history"].append({
        "role": "user",
        "content": user_text,
        "ts": int(_time.time()),
    })
    
    # Manteniamo solo gli ultimi 10 messaggi per non consumare troppi token
    if len(ai_runtime["history"]) > 10:
        ai_runtime["history"] = ai_runtime["history"][-10:]

    # Segnaliamo al frontend che il gufetto sta pensando...
    _set_ai_state(AI_STATUS_THINKING)

    try:
        # 2. Prepariamo i messaggi per OpenAI usando il prompt educativo
        age_group, activity_mode, language_target, learning_step = _get_edu_config()
        system_prompt = ai_system_prompt(age_group, activity_mode, language_target, learning_step)
        messages = [{"role": "system", "content": system_prompt}]
        # OpenAI expects only role/content fields
        for h in ai_runtime["history"]:
            messages.append({"role": h["role"], "content": h["content"]})

        # 3. Chiamata alle API di OpenAI
        response = client.chat.completions.create(
            model=ai_settings.get("model", "gpt-3.5-turbo"),
            messages=messages,
            temperature=float(ai_settings.get("temperature", 0.7)),
            max_tokens=300
        )
        
        ai_reply = response.choices[0].message.content.strip()

        # 4. Salviamo la risposta nella storia con timestamp
        ai_runtime["history"].append({
            "role": "assistant",
            "content": ai_reply,
            "ts": int(_time.time()),
        })
        # Trim again to keep the cap at 10 (including the just-added reply)
        if len(ai_runtime["history"]) > 10:
            ai_runtime["history"] = ai_runtime["history"][-10:]
        
        # 5. Generiamo l'audio se il TTS provider è OpenAI
        audio_url = None
        if ai_settings.get("tts_provider") == "openai":
            # Creiamo un hash del testo per la cache (così non paghiamo due volte per la stessa frase)
            text_hash = hashlib.md5(ai_reply.encode('utf-8')).hexdigest()
            audio_path = os.path.join(AI_TTS_CACHE_DIR, f"{text_hash}.mp3")
            
            if not os.path.exists(audio_path):
                tts_response = client.audio.speech.create(
                    model="tts-1",
                    voice="nova", # Voce adatta ai bambini
                    input=ai_reply
                )
                tts_response.stream_to_file(audio_path)
                
            audio_url = f"/api/ai/tts/{text_hash}.mp3"

    except Exception as e:
        err_msg = str(e)
        log(f"Errore OpenAI: {err_msg}", "error")
        log_event("ai", "error", "Errore risposta OpenAI", {"error": err_msg[:200]})
        _set_ai_state(AI_STATUS_ERROR, error=err_msg)
        return jsonify({"error": "Errore del provider AI. Riprova tra poco."}), 500

    # Fine elaborazione: speaking se c'è audio OpenAI, altrimenti idle
    next_state = AI_STATUS_SPEAKING if audio_url else AI_STATUS_IDLE
    _set_ai_state(next_state)

    return jsonify({
        "status": "ok",
        "reply": ai_reply,
        "audio_url": audio_url
    })

# =========================================================
# STOP AI
# =========================================================
@ai_bp.route("/ai/stop", methods=["POST"])
def api_ai_stop():
    """Stop current AI activity and reset to idle."""
    _set_ai_state(AI_STATUS_IDLE)
    return jsonify({"status": "ok"})

# =========================================================
# LISTENING STATE (per STT browser)
# =========================================================
@ai_bp.route("/ai/listen/start", methods=["POST"])
def api_ai_listen_start():
    """Signal that the browser STT is starting (updates state to listening)."""
    _set_ai_state(AI_STATUS_LISTENING)
    return jsonify({"status": "ok"})

@ai_bp.route("/ai/listen/stop", methods=["POST"])
def api_ai_listen_stop():
    """Signal that browser STT has stopped (revert to idle if still listening)."""
    if ai_runtime.get("status") == AI_STATUS_LISTENING:
        _set_ai_state(AI_STATUS_IDLE)
    return jsonify({"status": "ok"})

# =========================================================
# PULIZIA STORIA E LETTURA AUDIO TTS
# =========================================================
@ai_bp.route("/ai/clear-history", methods=["POST"])
@ai_bp.route("/ai/clear", methods=["POST"])
def api_ai_clear_history():
    """Clear chat history and reset state. Accessible at both /ai/clear-history and /ai/clear."""
    try:
        ai_runtime["history"] = []
        _set_ai_state(AI_STATUS_IDLE)
        bus.emit_notification("Memoria del Gufetto cancellata 🧹", "info")
        return jsonify({"status": "ok"})
    except Exception as e:
        log_event("ai", "error", "Reset chat fallito", {"error": str(e)})
        return jsonify({"error": "Reset chat fallito"}), 500

@ai_bp.route("/ai/tts/<filename>", methods=["GET"])
def api_ai_tts_serve(filename):
    """Serve il file audio generato da OpenAI"""
    safe_name = os.path.basename(filename)
    file_path = os.path.join(AI_TTS_CACHE_DIR, safe_name)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype="audio/mpeg")
    return jsonify({"error": "File non trovato"}), 404

# =========================================================
# EDUCATIONAL CONFIG ENDPOINT
# =========================================================
@ai_bp.route("/ai/edu/config", methods=["GET"])
def api_ai_edu_config_get():
    """Return the current educational AI configuration."""
    age_group, activity_mode, language_target, learning_step = _get_edu_config()
    return jsonify({
        "age_group": age_group,
        "activity_mode": activity_mode,
        "activity_mode_label": ACTIVITY_MODE_LABELS.get(activity_mode, activity_mode),
        "language_target": language_target,
        "language_target_label": LANGUAGE_NAMES_IT.get(language_target, language_target),
        "learning_step": learning_step,
        "valid_age_groups": sorted(VALID_AGE_GROUPS),
        "valid_activity_modes": sorted(VALID_ACTIVITY_MODES),
        "valid_language_targets": sorted(VALID_LANGUAGE_TARGETS),
    })

@ai_bp.route("/ai/edu/config", methods=["POST"])
def api_ai_edu_config_post():
    """Update the educational AI configuration with validation."""
    data = request.get_json(silent=True) or {}

    age_group = data.get("age_group", ai_settings.get("age_group", "bambino"))
    raw_mode = data.get("activity_mode", ai_settings.get("activity_mode", "free_conversation"))
    activity_mode = LEGACY_MODE_MAP.get(raw_mode, raw_mode)
    raw_lang = data.get("language_target", ai_settings.get("language_target", "english"))
    language_target = LEGACY_LANG_MAP.get(raw_lang, raw_lang)
    try:
        learning_step = max(1, int(data.get("learning_step", ai_settings.get("learning_step", 1))))
    except (TypeError, ValueError):
        learning_step = 1

    errors = _validate_edu_config(age_group, activity_mode, language_target, learning_step)
    if errors:
        log_event("ai", "warning", "Configurazione educativa non valida", {"errors": errors})
        return jsonify({"error": "Configurazione non valida", "details": errors}), 400

    ai_settings["age_group"] = age_group
    ai_settings["activity_mode"] = activity_mode
    ai_settings["language_target"] = language_target
    ai_settings["learning_step"] = learning_step
    _sync_legacy_edu_fields()
    save_json_direct(AI_SETTINGS_FILE, ai_settings)
    log(f"AI educativa: {age_group} / {activity_mode} / {language_target} step {learning_step}", "info")

    return jsonify({
        "status": "ok",
        "age_group": age_group,
        "activity_mode": activity_mode,
        "language_target": language_target,
        "learning_step": learning_step,
    })

def ai_age_profile_rules(age_group):
    """Communication style rules based on age group."""
    profiles = {
        "bambino": {
            "style": (
                "Usa frasi cortissime e semplici. Parla come a un bambino piccolo. "
                "Usa emoji e onomatopee (Uhuu! Wow! 🎉). Non usare parole difficili. "
                "Sii sempre allegro e incoraggiante."
            )
        },
        "ragazzo": {
            "style": (
                "Usa frasi chiare e un po' più articolate. Sii divertente e coinvolgente. "
                "Fai domande per stimolare la curiosità. Spiega le cose in modo interessante."
            )
        },
        "adulto": {
            "style": (
                "Parla in modo chiaro, diretto e amichevole. Puoi essere dettagliato. "
                "Tono maturo ma accessibile. Meno emoji, più sostanza."
            )
        },
    }
    return profiles.get(age_group, profiles["bambino"])


def ai_system_prompt(age_group, activity_mode="free_conversation",
                     language_target="english", learning_step=1):
    """Build the educational system prompt based on age group, activity mode,
    language target and learning step."""
    age_group = age_group if age_group in VALID_AGE_GROUPS else "bambino"
    activity_mode = LEGACY_MODE_MAP.get(activity_mode, activity_mode)
    activity_mode = activity_mode if activity_mode in VALID_ACTIVITY_MODES else "free_conversation"
    language_target = LEGACY_LANG_MAP.get(language_target, language_target)
    language_target = language_target if language_target in VALID_LANGUAGE_TARGETS else "english"
    try:
        learning_step = max(1, int(learning_step))
    except (TypeError, ValueError):
        learning_step = 1

    rules = ai_age_profile_rules(age_group)
    base = (
        f"Sei il Gufetto Magico, un assistente educativo simpatico e saggio.\n"
        f"Il tuo compito è educare, intrattenere e rassicurare.\n"
        f"Fascia utente: {age_group}.\n"
        f"{rules['style']}\n"
    )

    if activity_mode == "teaching_general":
        if age_group == "bambino":
            base += (
                "\nMODALITÀ INSEGNAMENTO: Spiega le cose in modo semplicissimo, come a un bambino piccolo. "
                "Usa esempi concreti e metafore semplici. Frasi brevi. Tanto entusiasmo!"
            )
        elif age_group == "ragazzo":
            base += (
                "\nMODALITÀ INSEGNAMENTO: Spiega in modo chiaro e coinvolgente. "
                "Usa analogie. Incoraggia le domande. Spiega il perché delle cose."
            )
        else:
            base += (
                "\nMODALITÀ INSEGNAMENTO: Fornisci spiegazioni complete e precise. "
                "Puoi fare riferimenti culturali e tecnici. Tono diretto e informativo."
            )

    elif activity_mode == "quiz":
        if age_group == "bambino":
            base += (
                "\nMODALITÀ QUIZ: Fai domande semplicissime con tono allegro e festoso. "
                "Dai sempre un incoraggiamento anche se sbaglia. Usa 'Bravo!' e 'Wow!' spesso."
            )
        elif age_group == "ragazzo":
            base += (
                "\nMODALITÀ QUIZ: Fai domande interessanti su argomenti vari. "
                "Sii divertente ma stimolante. Spiega la risposta corretta dopo ogni domanda."
            )
        else:
            base += (
                "\nMODALITÀ QUIZ: Proponi quiz su cultura generale, storia, scienza. "
                "Tono diretto. Spiega le risposte in dettaglio."
            )

    elif activity_mode == "math":
        if age_group == "bambino":
            base += (
                "\nMODALITÀ MATEMATICA: Proponi esercizi semplicissimi (addizioni e sottrazioni a una cifra). "
                "Usa oggetti concreti ('hai 3 mele e ne mangi 1...'). Celebra ogni risposta giusta."
            )
        elif age_group == "ragazzo":
            base += (
                "\nMODALITÀ MATEMATICA: Proponi esercizi di livello medio (moltiplicazioni, divisioni, frazioni). "
                "Spiega il procedimento passo dopo passo. Usa problemi pratici."
            )
        else:
            base += (
                "\nMODALITÀ MATEMATICA: Affronta argomenti più complessi (algebra, geometria, percentuali). "
                "Spiega i concetti con rigore ma chiarezza. Tono diretto."
            )

    elif activity_mode == "animal_sounds_games":
        if age_group == "bambino":
            base += (
                "\nMODALITÀ ANIMALI: Fai il verso di un animale (es. 'Miao! Miao!') e chiedi di indovinare. "
                "Oppure descrivi l'animale in modo divertente. Usa onomatopee e tanto entusiasmo!"
            )
        elif age_group == "ragazzo":
            base += (
                "\nMODALITÀ ANIMALI: Proponi curiosità sugli animali (dove vivono, cosa mangiano). "
                "Alterna giochi di versi con mini quiz sulle specie."
            )
        else:
            base += (
                "\nMODALITÀ ANIMALI: Condividi informazioni scientifiche sugli animali. "
                "Puoi fare quiz naturalistici o curiosità zoologiche."
            )

    elif activity_mode == "interactive_story":
        if age_group == "bambino":
            base += (
                "\nMODALITÀ STORIA: Racconta una storia magica e colorata. "
                "Dopo 2-3 frasi fermati e chiedi: 'Cosa fa adesso il protagonista? Sceglie A) o B)?'. "
                "Usa personaggi simpatici e situazioni fantastiche."
            )
        elif age_group == "ragazzo":
            base += (
                "\nMODALITÀ STORIA: Racconta una storia avventurosa o misteriosa. "
                "Ad ogni scena chiedi di scegliere come proseguire tra due opzioni. "
                "Crea suspense e momenti di sorpresa."
            )
        else:
            base += (
                "\nMODALITÀ STORIA: Proponi una storia narrativa complessa. "
                "Fermati ai punti di svolta e chiedi come il protagonista dovrebbe reagire. "
                "Tono narrativo maturo."
            )

    elif activity_mode == "foreign_languages":
        lang_name = LANGUAGE_NAMES_IT.get(language_target, language_target)
        if age_group == "bambino":
            if learning_step <= 2:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Insegna parole basilari in {lang_name} (animali, colori, numeri 1-10, saluti). "
                    f"Di' la parola in italiano, poi in {lang_name}, e chiedi di ripetere. "
                    "Tono giocoso e pieno di incoraggiamenti."
                )
            elif learning_step <= 4:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Insegna frasi semplicissime in {lang_name} (ciao, come ti chiami, quanti anni hai). "
                    "Usa ripetizione guidata. Tono festoso."
                )
            else:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Mini giochi di parole in {lang_name}. "
                    "Indovina la parola, trova il contrario, completa la frase. Sempre in modo giocoso."
                )
        elif age_group == "ragazzo":
            if learning_step <= 2:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Proponi vocabolario di base in {lang_name} con mini quiz lessicali. "
                    "Chiedi di tradurre semplici frasi dall'italiano."
                )
            elif learning_step <= 4:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Proponi mini dialoghi in {lang_name}. "
                    "Fai domande e aspetta la risposta. Correggi con gentilezza spiegando."
                )
            else:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Esercizi di comprensione in {lang_name}: leggi una frase e chiedi il significato, "
                    "o riassumi un micro-testo."
                )
        else:  # adulto
            if learning_step <= 2:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Insegna frasi pratiche in {lang_name} (viaggio, shopping, lavoro). "
                    "Tono diretto, niente infantilizzazione."
                )
            elif learning_step <= 4:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Proponi dialoghi pratici in {lang_name} su situazioni reali. "
                    "Correggi la grammatica quando necessario."
                )
            else:
                base += (
                    f"\nMODALITÀ LINGUE ({lang_name.upper()}) - Step {learning_step}: "
                    f"Conversazione avanzata in {lang_name}. "
                    "Argomenti di attualità, cultura, professione. Livello B1-B2."
                )

    # free_conversation: use only the age-group rules above (no extra instructions)

    base += "\n\nEvita contenuti inappropriati. Sii conciso (max 3-4 frasi per risposta)."
    return base

@ai_bp.route("/ai/play_game", methods=["POST"])
def api_ai_start_game():
    data = request.get_json(silent=True) or {}
    # Accept both legacy and new field names
    game_type = data.get("game_type") or data.get("activity_mode", "animal_sounds_games")
    lang = data.get("lang") or data.get("language_target", "english")

    age_group, activity_mode, language_target, learning_step = _get_edu_config()
    # Allow per-request overrides
    if game_type:
        activity_mode = LEGACY_MODE_MAP.get(game_type, game_type)
        if activity_mode not in VALID_ACTIVITY_MODES:
            activity_mode = "animal_sounds_games"
    if lang:
        language_target = LEGACY_LANG_MAP.get(lang, lang)
        if language_target not in VALID_LANGUAGE_TARGETS:
            language_target = "english"

    prompt = ai_system_prompt(age_group, activity_mode, language_target, learning_step)
    # The prompt will be used by the next /ai/chat call via ai_settings
    return jsonify({"status": "ok", "game_started": activity_mode, "prompt_preview": prompt[:120]})

