import uuid
import csv
import io
from copy import deepcopy
from flask import Blueprint, request, jsonify, Response
from core.state import state, alarms_list, alarms_lock, media_runtime, bus, save_json_direct
from config import ALARMS_FILE, STATE_FILE
from core.utils import log, run_cmd
from core.database import (
    get_daily_stats, get_top_figurines, get_hourly_stats,
    get_battery_history, get_all_stats_for_export,
)

settings_bp = Blueprint('settings', __name__)

# =========================================================
# SVEGLIE (Allarmi con giorni della settimana)
# =========================================================
@settings_bp.route("/alarms", methods=["GET"])
def get_alarms():
    with alarms_lock:
        return jsonify(deepcopy(alarms_list))

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
    
    with alarms_lock:
        alarms_list.append(new_alarm)
    bus.mark_dirty("alarms")
    bus.request_emit("public")
    log(f"Sveglia creata per le {new_alarm['hour']}:{new_alarm['minute']}", "info")
    return jsonify({"status": "ok", "alarm": new_alarm})

@settings_bp.route("/alarms/<alarm_id>", methods=["DELETE"])
def delete_alarm(alarm_id):
    with alarms_lock:
        alarms_list[:] = [a for a in alarms_list if str(a.get("id")) != str(alarm_id)]
    bus.mark_dirty("alarms")
    bus.request_emit("public")
    return jsonify({"status": "ok"})

@settings_bp.route("/alarms/<alarm_id>", methods=["PUT", "PATCH"])
def update_alarm(alarm_id):
    """Aggiorna una sveglia esistente (toggle enabled, cambio orario, giorni, label, target)."""
    data = request.get_json(silent=True) or {}
    with alarms_lock:
        for a in alarms_list:
            if str(a.get("id")) == str(alarm_id):
                if "enabled" in data:
                    a["enabled"] = bool(data["enabled"])
                if "hour" in data:
                    a["hour"] = int(data["hour"])
                if "minute" in data:
                    a["minute"] = int(data["minute"])
                if "days" in data:
                    a["days"] = data["days"]
                if "label" in data:
                    a["label"] = data["label"]
                if "target" in data:
                    a["target"] = data["target"]
                updated_alarm = deepcopy(a)
                bus.mark_dirty("alarms")
                bus.request_emit("public")
                log(f"Sveglia {alarm_id} aggiornata", "info")
                return jsonify({"status": "ok", "alarm": updated_alarm})
    return jsonify({"error": "Sveglia non trovata"}), 404

# =========================================================
# PARENTAL CONTROL (#9)
# =========================================================
@settings_bp.route("/parental/settings", methods=["GET"])
def get_parental_settings():
    parental = state.get("parental_control", {
        "enabled": False,
        "age_profile": "6-8",
        "daily_limit_minutes": 120,
        "allow_from": "08:00",
        "allow_to": "20:30",
        "max_volume": 80
    })
    # Ensure age_profile exists in older saved states
    if "age_profile" not in parental:
        parental = dict(parental)
        parental["age_profile"] = "6-8"
    return jsonify(parental)

@settings_bp.route("/parental/settings", methods=["POST"])
def save_parental_settings():
    data = request.get_json(silent=True) or {}

    from core.edu_config import VALID_AGE_PROFILES
    age_profile = str(data.get("age_profile", "6-8")).strip()
    if age_profile not in VALID_AGE_PROFILES:
        age_profile = "6-8"

    state["parental_control"] = {
        "enabled": bool(data.get("enabled", False)),
        "age_profile": age_profile,
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
# STATISTICHE (#11 + Analytics)
# =========================================================
@settings_bp.route("/stats/daily", methods=["GET"])
def api_daily_stats():
    """Recupera i dati dal DB SQLite per il grafico Vue (ultimi 7 giorni)"""
    return jsonify(get_daily_stats())

@settings_bp.route("/stats/top-figurines", methods=["GET"])
def api_top_figurines():
    """Classifica le statuine più usate per tempo di ascolto 🏆"""
    n = request.args.get("n", 5, type=int)
    n = max(1, min(20, n))  # Limite a 20 statuine: sufficiente per l'UI e le performance DB
    return jsonify(get_top_figurines(n))

@settings_bp.route("/stats/hourly", methods=["GET"])
def api_hourly_stats():
    """Distribuzione degli ascolti per fascia oraria (0-23) 🕐"""
    return jsonify(get_hourly_stats())

@settings_bp.route("/stats/battery-history", methods=["GET"])
def api_battery_history():
    """Storico percentuale batteria nel tempo 🔋"""
    hours = request.args.get("hours", 24, type=int)
    hours = max(1, min(48, hours))
    return jsonify(get_battery_history(hours))

@settings_bp.route("/stats/export", methods=["GET"])
def api_stats_export():
    """Esporta tutte le statistiche di ascolto in CSV o JSON 📤"""
    fmt = request.args.get("format", "json").lower()
    data = get_all_stats_for_export()

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["date", "hour", "rfid_uid", "duration_seconds"])
        writer.writeheader()
        writer.writerows(data)
        csv_content = output.getvalue()
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=gufobox_stats.csv"},
        )

    return jsonify(data)
