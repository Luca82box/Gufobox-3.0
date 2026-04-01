import uuid
from flask import Blueprint, request, jsonify
from core.state import state, alarms_list, media_runtime, bus, save_json_direct
from config import ALARMS_FILE, STATE_FILE
from core.utils import log, run_cmd
from core.database import get_daily_stats

settings_bp = Blueprint('settings', __name__)

# =========================================================
# SVEGLIE (Allarmi con giorni della settimana)
# =========================================================
@settings_bp.route("/alarms", methods=["GET"])
def get_alarms():
    return jsonify(alarms_list)

@settings_bp.route("/alarms", methods=["POST"])
def add_alarm():
    data = request.get_json(silent=True) or {}
    
    new_alarm = {
        "id": str(uuid.uuid4())[:8],
        "enabled": data.get("enabled", True),
        "hour": int(data.get("hour", 8)),
        "minute": int(data.get("minute", 0)),
        "days": data.get("days", [0, 1, 2, 3, 4, 5, 6]), # 0=Lun, 6=Dom
        "label": data.get("label", "Sveglia 🦉"),
        "target": data.get("target", "") # Percorso file o URL radio
    }
    
    alarms_list.append(new_alarm)
    bus.mark_dirty("alarms")
    bus.request_emit("public")
    log(f"Sveglia creata per le {new_alarm['hour']}:{new_alarm['minute']}", "info")
    return jsonify({"status": "ok", "alarm": new_alarm})

@settings_bp.route("/alarms/<alarm_id>", methods=["DELETE"])
def delete_alarm(alarm_id):
    global alarms_list
    alarms_list[:] = [a for a in alarms_list if str(a.get("id")) != str(alarm_id)]
    bus.mark_dirty("alarms")
    bus.request_emit("public")
    return jsonify({"status": "ok"})

# =========================================================
# PARENTAL CONTROL (#9)
# =========================================================
@settings_bp.route("/parental/settings", methods=["GET"])
def get_parental_settings():
    parental = state.get("parental_control", {
        "enabled": False,
        "daily_limit_minutes": 120,
        "allow_from": "08:00",
        "allow_to": "20:30",
        "max_volume": 80
    })
    return jsonify(parental)

@settings_bp.route("/parental/settings", methods=["POST"])
def save_parental_settings():
    data = request.get_json(silent=True) or {}
    
    state["parental_control"] = {
        "enabled": bool(data.get("enabled", False)),
        "daily_limit_minutes": int(data.get("daily_limit_minutes", 120)),
        "allow_from": data.get("allow_from", "08:00"),
        "allow_to": data.get("allow_to", "20:30"),
        "max_volume": int(data.get("max_volume", 80))
    }
    
    # Se il volume attuale supera il limite, lo abbassiamo forzatamente
    max_v = state["parental_control"]["max_volume"]
    if media_runtime["current_volume"] > max_v:
        media_runtime["current_volume"] = max_v
        run_cmd(["amixer", "sset", "Master", f"{max_v}%"])
        bus.mark_dirty("media")

    bus.mark_dirty("state")
    bus.request_emit("admin")
    bus.emit_notification("Restrizioni Parental Control aggiornate", "success")
    return jsonify({"status": "ok"})

# =========================================================
# STATISTICHE (#11)
# =========================================================
@settings_bp.route("/stats/daily", methods=["GET"])
def api_daily_stats():
    """Recupera i dati dal DB SQLite per il grafico Vue"""
    return jsonify(get_daily_stats())

