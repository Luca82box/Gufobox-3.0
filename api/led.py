import os
import re
import json
import time

from flask import Blueprint, request, jsonify
from core.state import led_runtime, bus, save_json_direct, now_ts
from core.utils import log
from config import LED_EFFECTS_CUSTOM_DIR, LED_MASTER_FILE

led_bp = Blueprint('led', __name__)

# =========================================================
# CATALOGO EFFETTI LED BUILTIN
# =========================================================
BUILTIN_LED_EFFECTS = {
    "off": {
        "id": "off",
        "name": "Spento",
        "builtin": True,
        "description": "LED spenti",
    },
    "solid": {
        "id": "solid",
        "name": "Colore fisso",
        "builtin": True,
        "description": "Un colore fisso su tutti i LED",
        "params": {"color": "#0000ff"},
    },
    "breathing": {
        "id": "breathing",
        "name": "Respiro",
        "builtin": True,
        "description": "Effetto respiro, luminosità oscillante",
        "params": {"color": "#00ff00", "speed": 30},
    },
    "blink": {
        "id": "blink",
        "name": "Lampeggio",
        "builtin": True,
        "description": "Lampeggio acceso/spento",
        "params": {"color": "#ffffff", "speed": 50},
    },
    "rainbow": {
        "id": "rainbow",
        "name": "Arcobaleno",
        "builtin": True,
        "description": "Scorrimento colori arcobaleno",
        "params": {"speed": 30},
    },
    "pulse": {
        "id": "pulse",
        "name": "Impulso",
        "builtin": True,
        "description": "Impulso rapido di luce",
        "params": {"color": "#ff9900", "speed": 60},
    },
    "random": {
        "id": "random",
        "name": "Casuale",
        "builtin": True,
        "description": "Colori casuali su ogni LED",
        "params": {"speed": 40},
    },
}

# =========================================================
# AI → LED MAP
# =========================================================
AI_LED_MAP = {
    "idle": {
        "enabled": True,
        "effect_id": "breathing",
        "color": "#0044ff",
        "brightness": 40,
        "speed": 20,
        "params": {},
    },
    "listening": {
        "enabled": True,
        "effect_id": "pulse",
        "color": "#00ff88",
        "brightness": 70,
        "speed": 60,
        "params": {},
    },
    "thinking": {
        "enabled": True,
        "effect_id": "breathing",
        "color": "#ffaa00",
        "brightness": 60,
        "speed": 40,
        "params": {},
    },
    "speaking": {
        "enabled": True,
        "effect_id": "solid",
        "color": "#44ddff",
        "brightness": 80,
        "speed": 30,
        "params": {},
    },
    "error": {
        "enabled": True,
        "effect_id": "blink",
        "color": "#ff2200",
        "brightness": 90,
        "speed": 70,
        "params": {},
    },
}

# =========================================================
# DEFAULT ASSIGNMENT
# =========================================================
DEFAULT_LED_ASSIGNMENT = {
    "enabled": True,
    "effect_id": "solid",
    "color": "#0000ff",
    "brightness": 70,
    "speed": 30,
    "params": {},
}

# =========================================================
# VALIDATION HELPERS
# =========================================================
_EFFECT_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')
_COLOR_HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _sanitize_effect_id(effect_id):
    """Valida e restituisce l'effect_id se sicuro, altrimenti None."""
    if _EFFECT_ID_RE.match(effect_id):
        return effect_id
    return None


def _safe_effect_path(safe_id):
    """
    Restituisce il percorso assoluto del file effetto.
    Usa os.path.basename per garantire che il nome non contenga separatori di path.
    Verifica anche tramite realpath che il percorso risultante sia dentro LED_EFFECTS_CUSTOM_DIR.
    """
    custom_root = os.path.realpath(LED_EFFECTS_CUSTOM_DIR)
    safe_filename = os.path.basename(f"{safe_id}.json")
    if not safe_filename.endswith(".json") or safe_filename == ".json":
        return None
    fpath = os.path.realpath(os.path.join(custom_root, safe_filename))
    if not fpath.startswith(custom_root + os.sep):
        return None
    return fpath


def validate_led_assignment(assignment):
    """
    Valida un LED assignment completo.
    Ritorna (True, None) se valido, (False, errore) altrimenti.
    """
    if not isinstance(assignment, dict):
        return False, "Assignment deve essere un oggetto JSON"
    effect_id = assignment.get("effect_id", "")
    if not isinstance(effect_id, str) or not effect_id:
        return False, "effect_id mancante o non valido"
    if not _sanitize_effect_id(effect_id):
        return False, "effect_id contiene caratteri non consentiti"
    color = assignment.get("color", "#000000")
    if not isinstance(color, str) or not _COLOR_HEX_RE.match(color):
        return False, f"Colore '{color}' non valido: usa formato #rrggbb"
    brightness = assignment.get("brightness", 70)
    if not isinstance(brightness, (int, float)) or not (0 <= brightness <= 100):
        return False, "brightness deve essere tra 0 e 100"
    speed = assignment.get("speed", 30)
    if not isinstance(speed, (int, float)) or not (0 <= speed <= 100):
        return False, "speed deve essere tra 0 e 100"
    params = assignment.get("params", {})
    if not isinstance(params, dict):
        return False, "params deve essere un oggetto JSON"
    return True, None


REQUIRED_EFFECT_FIELDS = {"id", "name"}

# Custom effect types that require extra shape validation
_CUSTOM_TYPES_REQUIRED = {
    "sequence": "steps",
    "random_mix": "pool",
    "scene": "slots",
}


def validate_custom_led_effect(data):
    """
    Valida un effetto LED custom (struttura JSON completa).
    Supporta tipi standard, sequence, random_mix, scene.
    Ritorna (True, None) o (False, messaggio).
    """
    if not isinstance(data, dict):
        return False, "L'effetto deve essere un oggetto JSON"
    missing = REQUIRED_EFFECT_FIELDS - set(data.keys())
    if missing:
        return False, f"Campi obbligatori mancanti: {missing}"
    effect_id = data.get("id")
    if not isinstance(effect_id, str) or not effect_id.strip():
        return False, "Il campo 'id' deve essere una stringa non vuota"
    if effect_id in BUILTIN_LED_EFFECTS:
        return False, f"L'id '{effect_id}' è riservato a un effetto builtin"
    if not _sanitize_effect_id(effect_id):
        return False, "effect_id contiene caratteri non consentiti"
    # Type-specific shape check
    etype = data.get("type")
    if etype in _CUSTOM_TYPES_REQUIRED:
        required_key = _CUSTOM_TYPES_REQUIRED[etype]
        items = data.get(required_key)
        if not isinstance(items, list) or len(items) == 0:
            return False, f"Effetto di tipo '{etype}' deve avere un array '{required_key}' non vuoto"
    params = data.get("params")
    if params is not None and not isinstance(params, dict):
        return False, "Il campo 'params' deve essere un oggetto JSON"
    return True, None


# Internal alias kept for backward compatibility with existing tests
_validate_custom_effect = validate_custom_led_effect


def load_custom_led_effects():
    """Carica tutti gli effetti LED custom dalla directory dedicata."""
    effects = {}
    if not os.path.isdir(LED_EFFECTS_CUSTOM_DIR):
        return effects
    for fname in os.listdir(LED_EFFECTS_CUSTOM_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(LED_EFFECTS_CUSTOM_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            ok, _ = validate_custom_led_effect(data)
            if ok:
                effects[data["id"]] = data
        except Exception as e:
            log(f"Errore lettura effetto LED custom {fname}: {e}", "warning")
    return effects


def _get_all_effects():
    """Restituisce builtin + custom uniti."""
    effects = dict(BUILTIN_LED_EFFECTS)
    effects.update(load_custom_led_effects())
    return effects


# =========================================================
# MASTER LED — stato persistente
# =========================================================
DEFAULT_LED_MASTER = {
    "enabled": True,
    "override_active": False,
    "settings": {
        "enabled": True,
        "effect_id": "solid",
        "color": "#0000ff",
        "brightness": 70,
        "speed": 30,
        "params": {},
    },
}


def load_led_master():
    if os.path.exists(LED_MASTER_FILE):
        try:
            with open(LED_MASTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Migrate old flat format to new nested format
            data = _migrate_master(data)
            return data
        except Exception as e:
            log(f"Errore lettura led_master: {e}", "warning")
    import copy
    return copy.deepcopy(DEFAULT_LED_MASTER)


def _migrate_master(data):
    """Migrates old flat master format to the new nested settings format."""
    if "settings" not in data:
        # Old flat format: promote flat fields into settings
        settings = {
            "enabled": data.get("enabled", True),
            "effect_id": data.get("effect_id", "solid"),
            "color": data.get("color", "#0000ff"),
            "brightness": data.get("brightness", 70),
            "speed": data.get("speed", 30),
            "params": data.get("params", {}),
        }
        # Resolve override field name
        override_active = data.get("override_active", data.get("override", False))
        return {
            "enabled": data.get("enabled", True),
            "override_active": override_active,
            "settings": settings,
        }
    # Ensure override_active key exists (migrate from old "override" key)
    if "override" in data and "override_active" not in data:
        data["override_active"] = data.pop("override")
    return data


def save_led_master(data):
    save_json_direct(LED_MASTER_FILE, data)


# =========================================================
# GERARCHIA SORGENTI LED
# =========================================================

def get_effective_led_assignment():
    """
    Calcola l'assignment LED effettivo secondo la gerarchia di priorità:
      1. AI state attivo
      2. Master override attivo
      3. Profilo RFID attivo con blocco LED
      4. Default di sistema
    Ritorna (assignment_dict, source_str).
    """
    from core.state import rfid_map

    # 1. AI state
    ai_state = led_runtime.get("ai_state")
    if ai_state and ai_state in AI_LED_MAP:
        return AI_LED_MAP[ai_state].copy(), "ai"

    # 2. Master override
    master = load_led_master()
    if master.get("override_active") and master.get("enabled", True):
        settings = master.get("settings", {})
        assignment = {
            "enabled": settings.get("enabled", True),
            "effect_id": settings.get("effect_id", "solid"),
            "color": settings.get("color", "#0000ff"),
            "brightness": int(settings.get("brightness", 70)),
            "speed": int(settings.get("speed", 30)),
            "params": settings.get("params", {}),
        }
        return assignment, "master"

    # 3. Active RFID profile with LED block
    current_rfid = led_runtime.get("current_rfid")
    if current_rfid:
        profile = rfid_map.get(current_rfid, {})
        led_block = profile.get("led")
        if led_block and led_block.get("enabled"):
            assignment = {
                "enabled": True,
                "effect_id": led_block.get("effect_id", "solid"),
                "color": led_block.get("color", "#ffffff"),
                "brightness": int(led_block.get("brightness", 70)),
                "speed": int(led_block.get("speed", 30)),
                "params": led_block.get("params", {}),
            }
            return assignment, "rfid"

    # 4. Default
    return DEFAULT_LED_ASSIGNMENT.copy(), "default"


def refresh_effective_led():
    """
    Ricalcola l'effetto LED effettivo secondo la gerarchia e aggiorna
    led_runtime e notifica l'EventBus.
    """
    assignment, source = get_effective_led_assignment()

    # Validate assignment; fall back to default on invalid
    ok, err = validate_led_assignment(assignment)
    if not ok:
        log(f"refresh_effective_led: assignment invalido ({err}), fallback a default", "warning")
        assignment = DEFAULT_LED_ASSIGNMENT.copy()
        source = "default"

    # Update new-style fields
    led_runtime["applied"] = assignment
    led_runtime["current_source"] = source
    led_runtime["master_override_active"] = source == "master"
    led_runtime["last_updated_ts"] = now_ts()

    # Update legacy fields for hw/led.py backward compatibility
    led_runtime["current_effect"] = assignment["effect_id"]
    led_runtime["master_color"] = assignment.get("color", "#0000ff")
    led_runtime["master_brightness"] = assignment.get("brightness", 70)
    led_runtime["master_speed"] = assignment.get("speed", 30)
    led_runtime["master_enabled"] = assignment.get("enabled", True)

    bus.mark_dirty("led")
    bus.request_emit("public")


# =========================================================
# ROTTE EFFETTI LED
# =========================================================

@led_bp.route("/led/effects", methods=["GET"])
def api_led_effects_get():
    """Restituisce il catalogo completo degli effetti (builtin + custom)."""
    effects = _get_all_effects()
    return jsonify({"effects": list(effects.values())})


@led_bp.route("/led/effects", methods=["POST"])
def api_led_effects_post():
    """Aggiunge un effetto LED custom via JSON nel body."""
    data = request.get_json(silent=True) or {}
    ok, err = validate_custom_led_effect(data)
    if not ok:
        return jsonify({"error": err}), 400

    effect_id = data["id"].strip()
    safe_id = _sanitize_effect_id(effect_id)
    if not safe_id:
        return jsonify({"error": "effect_id non valido: usa solo lettere, numeri, _ e -"}), 400
    fpath = _safe_effect_path(safe_id)
    if not fpath:
        return jsonify({"error": "effect_id non valido"}), 400
    data["id"] = safe_id
    data["builtin"] = False
    try:
        os.makedirs(LED_EFFECTS_CUSTOM_DIR, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log(f"Effetto LED custom '{safe_id}' salvato", "info")
    except Exception as e:
        log(f"Errore salvataggio effetto LED: {e}", "warning")
        return jsonify({"error": "Impossibile salvare l'effetto"}), 500

    return jsonify({"status": "ok", "effect_id": safe_id})


@led_bp.route("/led/effects/upload", methods=["POST"])
def api_led_effects_upload():
    """Carica un effetto LED custom da file JSON (multipart/form-data)."""
    if "file" not in request.files:
        return jsonify({"error": "Nessun file inviato"}), 400

    f = request.files["file"]
    if not f.filename.endswith(".json"):
        return jsonify({"error": "Il file deve essere in formato .json"}), 400

    try:
        data = json.load(f)
    except Exception:
        return jsonify({"error": "File JSON non valido"}), 400

    ok, err = validate_custom_led_effect(data)
    if not ok:
        return jsonify({"error": err}), 400

    effect_id = data["id"].strip()
    safe_id = _sanitize_effect_id(effect_id)
    if not safe_id:
        return jsonify({"error": "effect_id non valido: usa solo lettere, numeri, _ e -"}), 400
    fpath = _safe_effect_path(safe_id)
    if not fpath:
        return jsonify({"error": "effect_id non valido"}), 400
    data["id"] = safe_id
    data["builtin"] = False
    try:
        os.makedirs(LED_EFFECTS_CUSTOM_DIR, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        log(f"Effetto LED custom '{safe_id}' caricato da file", "info")
    except Exception as e:
        log(f"Errore salvataggio effetto LED da upload: {e}", "warning")
        return jsonify({"error": "Errore durante il salvataggio dell'effetto"}), 500

    return jsonify({"status": "ok", "effect_id": safe_id})


@led_bp.route("/led/effects/<effect_id>", methods=["DELETE"])
def api_led_effects_delete(effect_id):
    """Elimina un effetto LED custom (non si possono eliminare i builtin)."""
    safe_id = _sanitize_effect_id(effect_id)
    if not safe_id:
        return jsonify({"error": "effect_id non valido"}), 400
    if safe_id in BUILTIN_LED_EFFECTS:
        return jsonify({"error": "Non puoi eliminare un effetto builtin"}), 400

    fpath = _safe_effect_path(safe_id)
    if not fpath:
        return jsonify({"error": "effect_id non valido"}), 400
    if not os.path.exists(fpath):
        return jsonify({"error": "Effetto non trovato"}), 404

    try:
        os.remove(fpath)
        log(f"Effetto LED custom '{safe_id}' eliminato", "info")
    except Exception as e:
        log(f"Errore eliminazione effetto LED: {e}", "warning")
        return jsonify({"error": "Errore durante l'eliminazione dell'effetto"}), 500

    return jsonify({"status": "ok"})


@led_bp.route("/led/effects/test", methods=["POST"])
def api_led_effects_test():
    """
    Applica temporaneamente un effetto LED per anteprima.
    Payload: {"effect_id": "rainbow", "color": "#ff0000", "brightness": 80, "speed": 50}
    """
    data = request.get_json(silent=True) or {}
    effect_id = data.get("effect_id", "solid")
    all_effects = _get_all_effects()
    if effect_id not in all_effects:
        return jsonify({"error": f"Effetto '{effect_id}' non trovato"}), 404

    # Build a temporary assignment for preview (does not persist to master)
    color = data.get("color", led_runtime.get("master_color", "#0000ff"))
    brightness = int(data.get("brightness", led_runtime.get("master_brightness", 70)))
    speed = int(data.get("speed", led_runtime.get("master_speed", 30)))

    # Validate the test assignment
    test_assignment = {"effect_id": effect_id, "color": color, "brightness": brightness,
                       "speed": speed, "params": data.get("params", {})}
    ok, err = validate_led_assignment(test_assignment)
    if not ok:
        return jsonify({"error": err}), 400

    # Apply directly to runtime (temporary, not persisted)
    led_runtime["current_effect"] = effect_id
    led_runtime["master_color"] = color
    led_runtime["master_brightness"] = brightness
    led_runtime["master_speed"] = speed
    led_runtime["applied"] = {**test_assignment, "enabled": True}
    led_runtime["current_source"] = "test"
    led_runtime["last_updated_ts"] = now_ts()
    bus.mark_dirty("led")
    bus.request_emit("public")

    log(f"Test effetto LED: {effect_id}", "info")
    return jsonify({"status": "ok", "effect_id": effect_id})


# =========================================================
# MASTER LED
# =========================================================

@led_bp.route("/led/master", methods=["GET"])
def api_led_master_get():
    """Restituisce la configurazione master LED."""
    master = load_led_master()
    return jsonify(master)


@led_bp.route("/led/master", methods=["POST"])
def api_led_master_post():
    """
    Salva la configurazione master LED.
    Payload (nuovo formato):
      {"enabled": true, "override_active": false, "settings": {"effect_id": "rainbow", "color": "#ff9900", ...}}
    Oppure payload flat (backward compat):
      {"effect_id": "rainbow", "color": "#ff9900", "brightness": 70, "speed": 30}
    """
    data = request.get_json(silent=True) or {}
    master = load_led_master()

    all_effects = _get_all_effects()

    # Detect new nested format vs old flat format
    if "settings" in data:
        settings_in = data["settings"]
        if "enabled" in data:
            master["enabled"] = bool(data["enabled"])
        if "override_active" in data:
            master["override_active"] = bool(data["override_active"])
    else:
        # Backward compat: flat payload → treat as settings
        settings_in = data
        if "override_active" in data:
            master["override_active"] = bool(data["override_active"])
        elif "override" in data:
            master["override_active"] = bool(data["override"])

    # Apply settings fields
    settings = master.setdefault("settings", {})
    effect_id = settings_in.get("effect_id", settings.get("effect_id", "solid"))
    if effect_id not in all_effects:
        return jsonify({"error": f"Effetto '{effect_id}' non trovato"}), 400
    settings["effect_id"] = effect_id

    if "color" in settings_in:
        color = str(settings_in["color"])
        if not _COLOR_HEX_RE.match(color):
            return jsonify({"error": f"Colore '{color}' non valido"}), 400
        settings["color"] = color
    if "brightness" in settings_in:
        settings["brightness"] = max(0, min(100, int(settings_in["brightness"])))
    if "speed" in settings_in:
        settings["speed"] = max(0, min(100, int(settings_in["speed"])))
    if "enabled" in settings_in:
        settings["enabled"] = bool(settings_in["enabled"])
    if "params" in settings_in:
        settings["params"] = settings_in["params"]

    save_led_master(master)
    refresh_effective_led()

    log(f"Master LED aggiornato: {effect_id}", "info")
    return jsonify({"status": "ok", "master": master})


@led_bp.route("/led/master/override", methods=["POST"])
def api_led_master_override():
    """
    Attiva/disattiva l'override master LED.
    Payload: {"override_active": true}  oppure  {"override": true}  (compat)
    """
    data = request.get_json(silent=True) or {}
    # Accept both key names for backward compat
    override = bool(data.get("override_active", data.get("override", False)))
    master = load_led_master()
    master["override_active"] = override
    save_led_master(master)
    refresh_effective_led()

    log(f"Override LED master: {override}", "info")
    bus.emit_notification(
        f"Override LED {'attivato' if override else 'disattivato'}", "info"
    )
    return jsonify({"status": "ok", "override_active": override})


@led_bp.route("/led/status", methods=["GET"])
def api_led_status():
    """Restituisce lo stato LED attuale (runtime + master config)."""
    master = load_led_master()
    return jsonify({
        "runtime": led_runtime,
        "master": master,
        "override_active": master.get("override_active", False),
        "effective_effect": led_runtime.get("current_effect", "solid"),
        "current_source": led_runtime.get("current_source", "default"),
        "applied": led_runtime.get("applied", DEFAULT_LED_ASSIGNMENT.copy()),
        "current_rfid": led_runtime.get("current_rfid"),
        "ai_state": led_runtime.get("ai_state"),
        "last_updated_ts": led_runtime.get("last_updated_ts", 0),
    })


# =========================================================
# AI STATE → LED
# =========================================================

@led_bp.route("/led/ai_state", methods=["POST"])
def api_led_ai_state():
    """
    Aggiorna lo stato AI nel runtime LED e ricalcola l'effetto effettivo.
    Payload: {"state": "listening"}  oppure  {"state": null}  per resettare.
    Chiamata internamente da api/ai.py quando cambia lo stato AI.
    """
    data = request.get_json(silent=True) or {}
    ai_state = data.get("state")

    if ai_state is not None and ai_state not in AI_LED_MAP:
        return jsonify({"error": f"Stato AI '{ai_state}' non riconosciuto. "
                                  f"Valori validi: {list(AI_LED_MAP.keys())}"}), 400

    led_runtime["ai_state"] = ai_state
    refresh_effective_led()

    log(f"Stato AI LED aggiornato: {ai_state}", "info")
    return jsonify({"status": "ok", "ai_state": ai_state,
                    "current_source": led_runtime.get("current_source")})
