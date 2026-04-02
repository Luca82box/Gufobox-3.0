import os
import hashlib
from flask import Blueprint, request, jsonify, send_file

# Importiamo la configurazione e lo stato
from config import AI_SETTINGS_FILE, AI_TTS_CACHE_DIR, OPENAI_API_KEY
from core.state import ai_runtime, led_runtime, bus, load_json, save_json_direct
from core.utils import log

# Proviamo a importare OpenAI (se installato)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

ai_bp = Blueprint('ai', __name__)

# Carichiamo le impostazioni dell'AI (System prompt, voce, ecc.)
ai_settings = load_json(AI_SETTINGS_FILE, {
    "system_prompt": "Sei il Gufetto Magico, un assistente amichevole e saggio che parla ai bambini.",
    "temperature": 0.7,
    "tts_provider": "browser",
    "openai_api_key": OPENAI_API_KEY
})


def _set_ai_led_state(state):
    """
    Aggiorna lo stato AI nel runtime LED e ricalcola l'effetto effettivo.
    state: "idle" | "listening" | "thinking" | "speaking" | "error" | None
    """
    try:
        from api.led import refresh_effective_led
        led_runtime["ai_state"] = state
        refresh_effective_led()
    except Exception as e:
        log(f"Errore aggiornamento LED per stato AI '{state}': {e}", "warning")

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
        
    save_json_direct(AI_SETTINGS_FILE, ai_settings)
    log("Impostazioni AI aggiornate", "info")
    return jsonify({"status": "ok"})

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
        return jsonify({"error": "OpenAI non configurato. Inserisci la API Key nelle impostazioni."}), 500

    # 1. Aggiungiamo il messaggio dell'utente alla storia
    ai_runtime["history"].append({"role": "user", "content": user_text})
    
    # Manteniamo solo gli ultimi 10 messaggi per non consumare troppi token
    if len(ai_runtime["history"]) > 10:
        ai_runtime["history"] = ai_runtime["history"][-10:]

    # Segnaliamo al frontend che il gufetto sta pensando...
    ai_runtime["is_thinking"] = True
    bus.mark_dirty("ai")
    bus.request_emit("public")
    _set_ai_led_state("thinking")

    try:
        # 2. Prepariamo i messaggi per OpenAI
        messages = [{"role": "system", "content": ai_settings.get("system_prompt", "")}]
        messages.extend(ai_runtime["history"])

        # 3. Chiamata alle API di OpenAI
        response = client.chat.completions.create(
            model=ai_settings.get("model", "gpt-3.5-turbo"),
            messages=messages,
            temperature=float(ai_settings.get("temperature", 0.7)),
            max_tokens=300
        )
        
        ai_reply = response.choices[0].message.content.strip()

        # 4. Salviamo la risposta nella storia
        ai_runtime["history"].append({"role": "assistant", "content": ai_reply})
        
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
        log(f"Errore OpenAI: {e}", "error")
        ai_runtime["is_thinking"] = False
        bus.mark_dirty("ai")
        bus.request_emit("public")
        _set_ai_led_state("error")
        return jsonify({"error": str(e)}), 500

    # Fine elaborazione
    ai_runtime["is_thinking"] = False
    bus.mark_dirty("ai")
    bus.request_emit("public")
    _set_ai_led_state("speaking")

    return jsonify({
        "status": "ok",
        "reply": ai_reply,
        "audio_url": audio_url
    })

# =========================================================
# PULIZIA STORIA E LETTURA AUDIO TTS
# =========================================================
@ai_bp.route("/ai/clear-history", methods=["POST"])
def api_ai_clear_history():
    ai_runtime["history"] = []
    bus.mark_dirty("ai")
    bus.request_emit("public")
    bus.emit_notification("Memoria del Gufetto cancellata 🧹", "info")
    return jsonify({"status": "ok"})

@ai_bp.route("/ai/tts/<filename>", methods=["GET"])
def api_ai_tts_serve(filename):
    """Serve il file audio generato da OpenAI"""
    safe_name = os.path.basename(filename)
    file_path = os.path.join(AI_TTS_CACHE_DIR, safe_name)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype="audio/mpeg")
    return jsonify({"error": "File non trovato"}), 404

def ai_age_profile_rules(age_profile):
    """Regole di comunicazione basate sull'età"""
    profiles = {
        "bambino": {
            "style": "Usa frasi cortissime e semplici. Parla come a un bambino di 4 anni. Usa tanti emoji e onomatopee (Uhuu! Wow!). Non usare parole difficili."
        },
        "ragazzo": {
            "style": "Puoi usare frasi un po' più articolate. Fai battute simpatiche. Spiega le cose in modo curioso e coinvolgente."
        },
        "adulto": {
            "style": "Parla in modo chiaro e amichevole. Puoi essere più dettagliato nelle spiegazioni."
        }
    }
    return profiles.get(age_profile, profiles["bambino"])

def ai_system_prompt(age_profile, interactive_mode="chat_normale", target_lang="it"):
    rules = ai_age_profile_rules(age_profile)
    
    base = f"""Sei un piccolo gufetto magico, dolce e simpatico.
Il tuo compito principale è intrattenere, educare e rassicurare.
L'utente ha un'età stimata: {age_profile}.
{rules['style']}
"""
    # Gestione Modalità Interattive (#14)
    if interactive_mode == "quiz_animali":
        base += "\nMODALITÀ GIOCO: Fai il verso di un animale scrivendolo (es. 'Miao!') e chiedi al bambino di indovinare quale animale è. Attendi la risposta e fai i complimenti!"
    elif interactive_mode == "storia_interattiva":
        base += "\nMODALITÀ STORIA: Inizia a raccontare una storia, poi fermati e fai scegliere al bambino tra due opzioni su come farla proseguire."
    elif interactive_mode == "insegnante_lingue":
        base += f"\nMODALITÀ LINGUA: Devi insegnare qualche parola in {target_lang}. Dì una parola semplice in italiano, poi dilla in {target_lang} e chiedi al bambino di ripeterla."
    
    base += "\n\nEvita contenuti spaventosi. Sii brevissimo (max 2-3 frasi)."
    return base

@ai_bp.route("/ai/play_game", methods=["POST"])
def api_ai_start_game():
    data = request.get_json(silent=True) or {}
    game_type = data.get("game_type", "quiz_animali") # quiz_animali, storia_interattiva, insegnante_lingue
    lang = data.get("lang", "en") # en, es, de
    
    # Inizializza la conversazione con il prompt del gioco
    prompt = ai_system_prompt(ai_settings.get("age_profile", "bambino"), game_type, lang)
    # L'implementazione completa invierà questo prompt come primo messaggio al motore OpenAI...
    
    return jsonify({"status": "ok", "game_started": game_type})

