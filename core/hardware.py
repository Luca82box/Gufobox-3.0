import os
import eventlet
from datetime import datetime, timedelta

from core.state import media_runtime, alarms_list, bus, now_ts
from core.utils import log, run_cmd
from hw.amp import amp_on, amp_off

# ---------------------------------------------------------------------------
# Standby state machine
# ---------------------------------------------------------------------------
# Stati espliciti del ciclo di vita standby:
#   "awake"        — sistema operativo normale
#   "standby"      — standby profondo (player off, amp off, LED off, CPU powersave)
#   "waking"       — transizione standby → awake (operazioni wake in corso)
#   "alarm_active" — sveglia scattata, audio in riproduzione
STANDBY_AWAKE = "awake"
STANDBY_STANDBY = "standby"
STANDBY_WAKING = "waking"
STANDBY_ALARM_ACTIVE = "alarm_active"

_standby_state = STANDBY_AWAKE

# Debounce per le sveglie: ricorda (alarm_id, hour, minute) dell'ultimo scatto
# per evitare che lo stesso minuto faccia scattare più volte la stessa sveglia.
_alarm_last_fired: dict = {}


def is_in_standby() -> bool:
    """Compatibilità backward: ritorna True se il sistema è in stato standby."""
    return _standby_state == STANDBY_STANDBY


def get_standby_state() -> str:
    """Ritorna lo stato standby corrente come stringa esplicita."""
    return _standby_state


def perform_standby():
    """
    Mette la GufoBox in stato di standby a basso consumo.
    - Ferma player e amplificatore
    - Spegne LED
    - Riduce attività CPU
    - Mantiene attivo lo scheduler sveglie (il thread gira sempre)
    """
    global _standby_state
    from core.media import stop_player
    from hw.battery import play_ai_notification

    if _standby_state != STANDBY_AWAKE:
        log(f"perform_standby: stato corrente '{_standby_state}', non in awake — ignorato.", "warning")
        return

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

    _standby_state = STANDBY_STANDBY
    bus.request_emit("public")
    log("Standby logico attivato. Worker sveglie ancora attivo.", "info")
    try:
        from core.event_log import log_event as _lev
        _lev("standby", "info", "Standby attivato")
    except Exception:
        pass


def wake_from_standby():
    """
    Risveglia il sistema dallo standby logico.
    Chiamato dal pulsante fisico o dallo scheduler sveglie quando scatta un allarme.
    Transizione: standby → waking → awake
    """
    global _standby_state

    if _standby_state not in (STANDBY_STANDBY, STANDBY_WAKING):
        log(f"wake_from_standby: stato corrente '{_standby_state}', skip.", "warning")
        return

    _standby_state = STANDBY_WAKING
    log("Wake dallo standby: reinizializzazione hardware...", "info")

    run_cmd(["sudo", "rfkill", "unblock", "bluetooth"])
    run_cmd(["sudo", "cpufreq-set", "-g", "ondemand"])
    run_cmd(["sudo", "vcgencmd", "display_power", "1"])
    amp_on()

    # Riabilita LED
    from core.state import led_runtime
    led_runtime["master_enabled"] = True
    bus.mark_dirty("led")

    _standby_state = STANDBY_AWAKE
    bus.request_emit("public")
    log("Standby terminato — sistema sveglio.", "info")
    try:
        from core.event_log import log_event as _lev
        _lev("standby", "info", "Wake da standby completato")
    except Exception:
        pass
    from hw.battery import play_ai_notification
    play_ai_notification("Uhuu! Sono sveglio e pronto a giocare!")


def _wake_for_alarm():
    """
    Risveglio dedicato allo scatto di una sveglia.
    Transition: standby → waking → alarm_active
    Garantisce che amp e audio siano pronti prima della riproduzione.
    """
    global _standby_state

    if _standby_state == STANDBY_STANDBY:
        _standby_state = STANDBY_WAKING
        log("Wake per sveglia: reinizializzazione hardware...", "info")
        run_cmd(["sudo", "rfkill", "unblock", "bluetooth"])
        run_cmd(["sudo", "cpufreq-set", "-g", "ondemand"])
        run_cmd(["sudo", "vcgencmd", "display_power", "1"])
        amp_on()

        from core.state import led_runtime
        led_runtime["master_enabled"] = True
        bus.mark_dirty("led")

        log("Hardware riattivato per sveglia.", "info")

    _standby_state = STANDBY_ALARM_ACTIVE
    bus.request_emit("public")


def _sleep_timer_worker():
    """Controlla periodicamente se il timer di spegnimento è scaduto"""
    from core.utils import is_shutdown_requested
    while not is_shutdown_requested():
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
    Debounce: la stessa sveglia non viene eseguita più di una volta per minuto.
    """
    from core.media import start_player
    from core.utils import is_shutdown_requested

    while not is_shutdown_requested():
        eventlet.sleep(30)
        now = datetime.now()
        weekday = now.weekday()  # 0=Lun, 6=Dom
        slot = (now.hour, now.minute)  # chiave di debounce per questo minuto

        for alarm in list(alarms_list):
            if not alarm.get("enabled"):
                continue
            if alarm.get("hour") != now.hour or alarm.get("minute") != now.minute:
                continue
            days = alarm.get("days", list(range(7)))
            if weekday not in days:
                continue

            alarm_id = alarm.get("id")
            # Debounce: salta se questa sveglia è già scattata in questo minuto
            if _alarm_last_fired.get(alarm_id) == slot:
                log(f"Sveglia {alarm_id} già eseguita per {slot}, skip debounce.", "debug")
                continue
            _alarm_last_fired[alarm_id] = slot

            target = alarm.get("target", "")
            log(f"Sveglia scattata! id={alarm_id} target={target}", "info")
            try:
                from core.event_log import log_event as _lev
                _lev("standby", "info", f"Sveglia scattata (id={alarm_id})", {"alarm_id": alarm_id, "target": target})
            except Exception:
                pass

            # Risveglio hardware dedicato per la sveglia
            _wake_for_alarm()
            eventlet.sleep(2)  # Pausa anti-pop per amp

            if target:
                start_player(target, mode="audio_only")

            # Dopo aver avviato il player, passa ad awake
            global _standby_state
            _standby_state = STANDBY_AWAKE
            bus.request_emit("public")
            bus.emit_notification("⏰ Sveglia!", "info")


def init_hardware_workers():
    """Avvia i worker hardware in background"""
    log("Avvio worker hardware (Sleep Timer, Alarm)...", "info")
    eventlet.spawn(_sleep_timer_worker)
    eventlet.spawn(_alarm_worker)

