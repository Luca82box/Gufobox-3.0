from flask import Blueprint, request, jsonify
from core.state import media_runtime, alarms_list, bus, now_ts
from core.utils import run_cmd, t, log
from core.hardware import perform_standby

# Creiamo il Blueprint per le rotte di sistema
system_bp = Blueprint('system', __name__)

# =========================================================
# GESTIONE ALIMENTAZIONE (Standby, Reboot)
# =========================================================
@system_bp.route("/system", methods=["POST"])
def api_system():
    data = request.get_json(silent=True) or {}
    azione = str(data.get("azione", "")).strip().lower()
    
    if azione == "standby":
        # Richiama la funzione hardware isolata che spegne le periferiche
        perform_standby()
        return jsonify({"status": "ok", "message": t("ok_standby")})
        
    elif azione == "reboot":
        log("Comando di riavvio ricevuto", "info")
        bus.emit_notification("Riavvio in corso... 🔄", "warning")
        run_cmd(["sudo", "reboot"])
        return jsonify({"status": "ok", "message": t("ok_reboot")})
        
    return jsonify({"status": "ok"})

# =========================================================
# SLEEP TIMER (Spegnimento automatico)
# =========================================================
@system_bp.route("/system/sleep_timer", methods=["POST"])
def api_sleep_timer():
    data = request.get_json(silent=True) or {}
    minutes = data.get("minutes", 0)
    
    try:
        minutes = int(minutes)
    except ValueError:
        minutes = 0

    if minutes > 0:
        # Calcola il timestamp futuro in cui spegnersi
        media_runtime["sleep_timer_target_ts"] = now_ts() + (minutes * 60)
        bus.emit_notification(f"Spegnimento tra {minutes} minuti 🌙", "info")
        log(f"Sleep timer impostato a {minutes} minuti", "info")
    else:
        # Disattiva il timer
        media_runtime["sleep_timer_target_ts"] = None
        bus.emit_notification("Timer disattivato", "info")
        log("Sleep timer disattivato", "info")
        
    # Avvisa l'EventBus del cambiamento
    bus.mark_dirty("media")
    bus.request_emit("public")
    
    return jsonify({
        "status": "ok", 
        "sleep_timer_target_ts": media_runtime.get("sleep_timer_target_ts")
    })

# =========================================================
# SNOOZE (Posticipo Sveglia)
# =========================================================
@system_bp.route("/alarms/<alarm_id>/snooze", methods=["POST"])
def api_alarm_snooze(alarm_id):
    """
    Posticipa la sveglia di 10 minuti. 
    Questa rotta verrà chiamata anche dal demone dei pulsanti fisici (GPIO).
    """
    from core.media import stop_player # Import locale per evitare conflitti
    
    for a in alarms_list:
        if str(a.get("id")) == str(alarm_id):
            # Aggiunge 10 minuti all'orario attuale della sveglia
            a["minute"] = (a.get("minute", 0) + 10) % 60
            
            # Se scatta l'ora successiva
            if a["minute"] < 10: 
                a["hour"] = (a.get("hour", 0) + 1) % 24
            
            # Ferma la musica che sta suonando ora
            stop_player()
            
            # Salva e avvisa il frontend
            bus.mark_dirty("alarms")
            bus.request_emit("public")
            bus.emit_notification("Sveglia posposta di 10 minuti ⏰", "info")
            log(f"Sveglia {alarm_id} posposta alle {a['hour']:02d}:{a['minute']:02d}", "info")
            
            return jsonify({"status": "ok", "message": "Snoozed"})
            
    return jsonify({"error": "Sveglia non trovata"}), 404

