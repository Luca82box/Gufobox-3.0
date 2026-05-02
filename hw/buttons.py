from gpiozero import Button
from core.utils import log

# =========================================================
# CONFIGURAZIONE PIN (Dalla tua scheda tecnica 2026)
# =========================================================
PIN_PLAY_PAUSE = 5   # GPIO5 (Pin 29)
PIN_NEXT       = 6   # GPIO6 (Pin 31)
PIN_PREV       = 13  # GPIO13 (Pin 33)
PIN_POWER      = 3   # GPIO3 (Pin 5) - Accensione / Standby

# URL delle API locali (usato solo nel fallback HTTP)
API_BASE = "http://127.0.0.1:5000/api"

# =========================================================
# Import diretto delle funzioni core (come fatto in hw/rfid.py)
# Fallback HTTP se l'import diretto non è disponibile
# =========================================================
try:
    from core.media import send_mpv_command as _send_mpv_command
    from core.hardware import perform_standby as _perform_standby
    from core.hardware import wake_from_standby as _wake_from_standby
    from core.hardware import is_in_standby as _is_in_standby
    from core.state import media_runtime as _media_runtime, state as _state, alarms_lock as _alarms_lock
    from core.utils import run_cmd as _run_cmd
    _DIRECT_AVAILABLE = True
except Exception as _e:
    log(f"Import diretto core non disponibile, uso fallback HTTP: {_e}", "warning")
    _send_mpv_command = None
    _perform_standby = None
    _wake_from_standby = None
    _is_in_standby = None
    _media_runtime = None
    _state = None
    _alarms_lock = None
    _run_cmd = None
    _DIRECT_AVAILABLE = False

# =========================================================
# AZIONI DEI PULSANTI
# =========================================================
def action_play_pause():
    log("Pulsante FISICO: Play/Pausa", "info")
    if _DIRECT_AVAILABLE:
        try:
            # Se una registrazione statuina è in corso → fermala
            try:
                from core.voice_recorder import is_statuina_recording, stop_statuina_recording
                if is_statuina_recording():
                    log("Pulsante FISICO: Play/Pausa → stop registrazione statuina", "info")
                    stop_statuina_recording()
                    return
            except Exception as _ve:
                log(f"Controllo registrazione statuina fallito: {_ve}", "warning")

            # Se sveglia attiva → snooze 5 minuti
            from core.hardware import get_standby_state
            if get_standby_state() == "alarm_active":
                log("Pulsante FISICO: Play -> Snooze sveglia 5 minuti", "info")
                from core.media import stop_player
                stop_player()
                # Posponi la sveglia attiva di 5 minuti
                from core.state import alarms_list, bus
                from datetime import datetime
                now = datetime.now()
                with _alarms_lock:
                    for a in alarms_list:
                        if a.get("enabled") and a.get("hour") == now.hour and abs(a.get("minute", -99) - now.minute) <= 1:
                            a["minute"] = (a.get("minute", 0) + 5) % 60
                            if a["minute"] < 5:
                                a["hour"] = (a.get("hour", 0) + 1) % 24
                            bus.mark_dirty("alarms")
                            break
                _wake_from_standby("button")
                bus.emit_notification("Sveglia posposta di 5 minuti ⏰", "info")
                try:
                    from hw.battery import play_ai_notification
                    play_ai_notification("Ancora 5 minutini... Zzz...")
                except Exception:
                    pass
                return

            _send_mpv_command(["cycle", "pause"])
            return
        except Exception as e:
            log(f"Chiamata diretta play/pause fallita, provo HTTP: {e}", "warning")
    try:
        import requests
        requests.post(f"{API_BASE}/media/toggle_pause", timeout=2)
    except Exception as e:
        log(f"Errore chiamata Play/Pausa: {e}", "warning")

def action_next():
    log("Pulsante FISICO: Traccia Successiva", "info")
    if _DIRECT_AVAILABLE:
        try:
            _send_mpv_command(["playlist-next"])
            return
        except Exception as e:
            log(f"Chiamata diretta next fallita, provo HTTP: {e}", "warning")
    try:
        import requests
        requests.post(f"{API_BASE}/media/next", timeout=2)
    except Exception as e:
        log(f"Errore nella richiesta media/next: {e}", "warning")

def action_prev():
    log("Pulsante FISICO: Traccia Precedente", "info")
    if _DIRECT_AVAILABLE:
        try:
            _send_mpv_command(["playlist-prev"])
            return
        except Exception as e:
            log(f"Chiamata diretta prev fallita, provo HTTP: {e}", "warning")
    try:
        import requests
        requests.post(f"{API_BASE}/media/prev", timeout=2)
    except Exception as e:
        log(f"Errore nella richiesta media/prev: {e}", "warning")

def action_power_hold():
    """Pressione lunga Power: no-op (standby solo da pannello admin)."""
    log("Pulsante FISICO: Power (Hold) -> Ignorato (standby solo da admin)", "debug")

def action_power_press():
    """Pressione singola Power:
    - Se in standby → wake
    - Se sveglia attiva → disattiva sveglia (stop player)
    - Se sveglio → shutdown completo del SO
    """
    if not _DIRECT_AVAILABLE:
        return
    try:
        from core.hardware import get_standby_state
        current_state = get_standby_state()

        if current_state == "standby":
            log("Pulsante FISICO: Power (Press) -> Wake da standby", "info")
            _wake_from_standby()
        elif current_state == "alarm_active":
            log("Pulsante FISICO: Power (Press) -> Disattiva sveglia", "info")
            from core.media import stop_player
            stop_player()
            from core.state import bus
            _wake_from_standby("button")
            bus.emit_notification("Sveglia disattivata 🦉", "info")
        else:
            log("Pulsante FISICO: Power (Press) -> Shutdown completo SO", "warning")
            from core.state import bus
            bus.emit_notification("Spegnimento in corso... 🔌", "warning")
            try:
                from hw.battery import play_ai_notification
                play_ai_notification("Zzz... il gufetto va a dormire! A presto amichetto!")
                import eventlet
                eventlet.sleep(3)
            except Exception:
                pass
            _run_cmd(["sudo", "shutdown", "-h", "now"])
    except Exception as e:
        log(f"Errore power press: {e}", "warning")

# =========================================================
# Quando tieni premuto il tasto, gpiozero chiamerà questa funzione di continuo
def action_volume_up():
    if _DIRECT_AVAILABLE:
        try:
            max_vol = 100
            try:
                pc = _state.get("parental_control", {})
                max_vol = pc.get("max_volume", 100)
            except Exception:
                pass
            vol = _media_runtime.get("current_volume", 60)
            new_vol = min(max_vol, vol + 5)
            _run_cmd(["amixer", "sset", "Master", f"{new_vol}%"])
            _media_runtime["current_volume"] = new_vol
            log("Pulsante FISICO: Volume +", "debug")
            return
        except Exception as e:
            log(f"Chiamata diretta volume+ fallita, provo HTTP: {e}", "warning")
    try:
        import requests
        r = requests.get(f"{API_BASE}/volume", timeout=1)
        vol = r.json().get("volume", 60)
        requests.post(f"{API_BASE}/volume", json={"volume": min(100, vol + 5)}, timeout=1)
        log("Pulsante FISICO: Volume +", "debug")
    except Exception as e:
        log(f"Errore nell'aumento del volume: {e}", "warning")

def action_volume_down():
    if _DIRECT_AVAILABLE:
        try:
            vol = _media_runtime.get("current_volume", 60)
            new_vol = max(0, vol - 5)
            _run_cmd(["amixer", "sset", "Master", f"{new_vol}%"])
            _media_runtime["current_volume"] = new_vol
            log("Pulsante FISICO: Volume -", "debug")
            return
        except Exception as e:
            log(f"Chiamata diretta volume- fallita, provo HTTP: {e}", "warning")
    try:
        import requests
        r = requests.get(f"{API_BASE}/volume", timeout=1)
        vol = r.json().get("volume", 60)
        requests.post(f"{API_BASE}/volume", json={"volume": max(0, vol - 5)}, timeout=1)
        log("Pulsante FISICO: Volume -", "debug")
    except Exception as e:
        log(f"Errore nella riduzione del volume: {e}", "warning")

# =========================================================
# INIZIALIZZAZIONE HARDWARE
# =========================================================
def init_buttons():
    log("Inizializzazione driver Pulsanti GPIO...", "info")
    try:
        # I tasti fisici. hold_time è il tempo (in sec) prima che si attivi l'azione "volume"
        btn_play = Button(PIN_PLAY_PAUSE, bounce_time=0.1)
        btn_next = Button(PIN_NEXT, hold_time=0.6, hold_repeat=True, bounce_time=0.1)
        btn_prev = Button(PIN_PREV, hold_time=0.6, hold_repeat=True, bounce_time=0.1)
        btn_power = Button(PIN_POWER, hold_time=3.0, bounce_time=0.1)

        # Assegnazione Click normali
        btn_play.when_pressed = action_play_pause
        btn_next.when_released = action_next # Usiamo release per non confonderlo con l'hold del volume
        btn_prev.when_released = action_prev

        # Pressione singola su Power: wake da standby (se in standby)
        btn_power.when_pressed = action_power_press

        # Assegnazione Pressione Lunga (Hold)
        btn_next.when_held = action_volume_up
        btn_prev.when_held = action_volume_down
        btn_power.when_held = action_power_hold
        
    except Exception as e:
        log(f"Impossibile inizializzare i pulsanti: {e}", "error")
