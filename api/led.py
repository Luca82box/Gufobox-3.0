import os
import re
import json
import uuid

from flask import Blueprint, request, jsonify
from core.state import led_runtime, bus, save_json_direct
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
}

_EFFECT_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')


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
    # os.path.basename è riconosciuto come sanitizzatore path da CodeQL
    safe_filename = os.path.basename(f"{safe_id}.json")
    if not safe_filename.endswith(".json") or safe_filename == ".json":
        return None
    fpath = os.path.realpath(os.path.join(custom_root, safe_filename))
    if not fpath.startswith(custom_root + os.sep):
        return None
    return fpath


REQUIRED_EFFECT_FIELDS = {"id", "name"}


def _validate_custom_effect(data):
    """Valida un effetto LED custom caricato da file JSON."""
    if not isinstance(data, dict):
        return False, "L'effetto deve essere un oggetto JSON"
    missing = REQUIRED_EFFECT_FIELDS - set(data.keys())
    if missing:
        return False, f"Campi obbligatori mancanti: {missing}"
    if not isinstance(data.get("id"), str) or not data["id"].strip():
        return False, "Il campo 'id' deve essere una stringa non vuota"
    if data["id"] in BUILTIN_LED_EFFECTS:
        return False, f"L'id '{data['id']}' è riservato a un effetto builtin"
    return True, None


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
            ok, _ = _validate_custom_effect(data)
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
    "effect_id": "solid",
    "color": "#0000ff",
    "brightness": 70,
    "speed": 30,
    "override": False,
    "params": {},
}


def load_led_master():
    if os.path.exists(LED_MASTER_FILE):
        try:
            with open(LED_MASTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            log(f"Errore lettura led_master: {e}", "warning")
    return dict(DEFAULT_LED_MASTER)


def save_led_master(data):
    save_json_direct(LED_MASTER_FILE, data)


def refresh_effective_led():
    """
    Ricalcola l'effetto LED effettivo in base a override master / RFID / default.
    Aggiorna led_runtime e notifica l'EventBus.
    """
    master = load_led_master()
    if master.get("override"):
        led_runtime["current_effect"] = master.get("effect_id", "solid")
        led_runtime["master_color"] = master.get("color", "#0000ff")
        led_runtime["master_brightness"] = master.get("brightness", 70)
        led_runtime["master_speed"] = master.get("speed", 30)
    # Se non c'è override, l'effetto RFID corrente (impostato da rfid_trigger) rimane
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
    ok, err = _validate_custom_effect(data)
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

    ok, err = _validate_custom_effect(data)
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

    led_runtime["current_effect"] = effect_id
    if "color" in data:
        led_runtime["master_color"] = data["color"]
    if "brightness" in data:
        led_runtime["master_brightness"] = int(data["brightness"])
    if "speed" in data:
        led_runtime["master_speed"] = int(data["speed"])
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
    Payload: {"effect_id": "rainbow", "color": "#ff9900", "brightness": 70, "speed": 30}
    """
    data = request.get_json(silent=True) or {}
    master = load_led_master()

    all_effects = _get_all_effects()
    effect_id = data.get("effect_id", master.get("effect_id", "solid"))
    if effect_id not in all_effects:
        return jsonify({"error": f"Effetto '{effect_id}' non trovato"}), 400

    master["effect_id"] = effect_id
    if "color" in data:
        master["color"] = str(data["color"])
    if "brightness" in data:
        master["brightness"] = max(0, min(100, int(data["brightness"])))
    if "speed" in data:
        master["speed"] = max(0, min(100, int(data["speed"])))
    if "enabled" in data:
        master["enabled"] = bool(data["enabled"])
    if "params" in data:
        master["params"] = data["params"]

    save_led_master(master)
    refresh_effective_led()

    log(f"Master LED aggiornato: {effect_id}", "info")
    return jsonify({"status": "ok", "master": master})


@led_bp.route("/led/master/override", methods=["POST"])
def api_led_master_override():
    """
    Attiva/disattiva l'override master LED.
    Quando override è True, il master LED prevale sugli effetti RFID.
    Payload: {"override": true}
    """
    data = request.get_json(silent=True) or {}
    override = bool(data.get("override", False))
    master = load_led_master()
    master["override"] = override
    save_led_master(master)
    refresh_effective_led()

    log(f"Override LED master: {override}", "info")
    bus.emit_notification(
        f"Override LED {'attivato' if override else 'disattivato'}", "info"
    )
    return jsonify({"status": "ok", "override": override})


@led_bp.route("/led/status", methods=["GET"])
def api_led_status():
    """Restituisce lo stato LED attuale (runtime + master config)."""
    master = load_led_master()
    return jsonify({
        "runtime": led_runtime,
        "master": master,
        "override_active": master.get("override", False),
        "effective_effect": led_runtime.get("current_effect", "solid"),
    })
