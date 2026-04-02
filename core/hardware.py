import os
import eventlet
from datetime import datetime, timedelta

from core.state import media_runtime, alarms_list, bus, now_ts
from core.utils import log, run_cmd
from hw.amp import amp_on, amp_off

# Flag in RAM per stato standby logico
_in_standby = False


def is_in_standby():
    return _in_standby


def perform_standby():
    """
    Mette la GufoBox in stato di standby a basso consumo.
    - Ferma player e amplificatore
    - Spegne LED
    - Riduce attività CPU
    - Mantiene attivo lo scheduler sveglie (il thread gira sempre)
    """
    global _in_standby
    from core.media import stop_player
    from hw.battery import play_ai_notification

    bus.emit_notification("GufoBox in Standby profondo... 🌙", "warning")
    play_ai_notification("Uhuu, che sonno! Faccio un pisolino. A dopo!")
    eventlet.sleep(3)

    stop_player()
    amp_off()

    # Spegne LED
    from core.state import led_runtime
    led_runtime["master_enabled"] = False
    bus.mark_dirty("led")

    # Disabilita radio (best-effort, non blocca il Wi-Fi se è l'unica interfaccia attiva)
    log("Tentativo disabilitazione radio non-wifi...", "info")
    run_cmd(["sudo", "rfkill", "block", "bluetooth"])

    # Risparmio energetico CPU
    run_cmd(["sudo", "cpufreq-set", "-g", "powersave"])

    # Disattiva HDMI
    run_cmd(["sudo", "vcgencmd", "display_power", "0"])

    _in_standby = True
    log("Standby logico attivato. Worker sveglie ancora attivo.", "info")


def wake_from_standby():
    """
    Risveglia il sistema dallo standby logico.
    Chiamato dal pulsante fisico o dallo scheduler sveglie quando scatta un allarme.
    """
    global _in_standby

    run_cmd(["sudo", "rfkill", "unblock", "bluetooth"])
    run_cmd(["sudo", "cpufreq-set", "-g", "ondemand"])
    run_cmd(["sudo", "vcgencmd", "display_power", "1"])
    amp_on()

    # Riabilita LED
    from core.state import led_runtime
    led_runtime["master_enabled"] = True
    bus.mark_dirty("led")
    bus.request_emit("public")

    _in_standby = False
    log("Standby terminato — sistema sveglio.", "info")
    from hw.battery import play_ai_notification
    play_ai_notification("Uhuu! Sono sveglio e pronto a giocare!")

def _sleep_timer_worker():
    """Controlla periodicamente se il timer di spegnimento è scaduto"""
    while True:
        eventlet.sleep(10)
        target = media_runtime.get("sleep_timer_target_ts")
        if target and now_ts() >= target:
            log("Sleep timer scaduto! Attivazione standby.", "info")
            media_runtime["sleep_timer_target_ts"] = None
            bus.mark_dirty("media")
            bus.request_emit("public")
            perform_standby()


def _alarm_worker():
    """
    Controlla periodicamente le sveglie.
    Se è in standby, risveglia il sistema prima di riprodurre l'audio.
    """
    from core.media import start_player

    while True:
        eventlet.sleep(30)
        now = datetime.now()
        weekday = now.weekday()  # 0=Lun, 6=Dom
        for alarm in list(alarms_list):
            if not alarm.get("enabled"):
                continue
            if alarm.get("hour") != now.hour or alarm.get("minute") != now.minute:
                continue
            days = alarm.get("days", list(range(7)))
            if weekday not in days:
                continue
            target = alarm.get("target", "")
            log(f"Sveglia scattata! target={target}", "info")
            if is_in_standby():
                wake_from_standby()
                eventlet.sleep(2)
            if target:
                start_player(target, mode="audio_only")
            bus.emit_notification("⏰ Sveglia!", "info")

def init_hardware_workers():
    """Avvia i worker hardware in background"""
    log("Avvio worker hardware (Sleep Timer, Alarm)...", "info")
    eventlet.spawn(_sleep_timer_worker)
    eventlet.spawn(_alarm_worker)

