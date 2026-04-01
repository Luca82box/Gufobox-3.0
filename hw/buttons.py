import requests
from gpiozero import Button
from core.utils import log

# =========================================================
# CONFIGURAZIONE PIN (Dalla tua scheda tecnica 2026)
# =========================================================
PIN_PLAY_PAUSE = 5   # GPIO5 (Pin 29)
PIN_NEXT       = 6   # GPIO6 (Pin 31)
PIN_PREV       = 13  # GPIO13 (Pin 33)
PIN_POWER      = 3   # GPIO3 (Pin 5) - Accensione / Standby

# URL delle API locali che abbiamo appena creato
API_BASE = "http://127.0.0.1:5000/api"

# =========================================================
# AZIONI DEI PULSANTI (Chiamano le API Flask)
# =========================================================
def action_play_pause():
    log("Pulsante FISICO: Play/Pausa", "info")
    try:
        requests.post(f"{API_BASE}/media/toggle_pause", timeout=2)
    except Exception as e:
        log(f"Errore chiamata Play/Pausa: {e}", "warning")

def action_next():
    log("Pulsante FISICO: Traccia Successiva", "info")
    try:
        requests.post(f"{API_BASE}/media/next", timeout=2)
    except Exception as e:
        log(f"Errore nella richiesta media/next: {e}", "warning")

def action_prev():
    log("Pulsante FISICO: Traccia Precedente", "info")
    try:
        requests.post(f"{API_BASE}/media/prev", timeout=2)
    except Exception as e:
        log(f"Errore nella richiesta media/prev: {e}", "warning")

def action_power_hold():
    """Tenendo premuto il tasto Power per 3 secondi andiamo in Standby"""
    log("Pulsante FISICO: Power (Hold) -> Standby", "warning")
    try:
        requests.post(f"{API_BASE}/system", json={"azione": "standby"}, timeout=2)
    except Exception as e:
        log(f"Errore nella richiesta standby: {e}", "warning")
# =========================================================
# Quando tieni premuto il tasto, gpiozero chiamerà questa funzione di continuo
def action_volume_up():
    try:
        # Leggiamo il volume attuale
        r = requests.get(f"{API_BASE}/volume", timeout=1)
        vol = r.json().get("volume", 60)
        # Lo alziamo di 5
        requests.post(f"{API_BASE}/volume", json={"volume": min(100, vol + 5)}, timeout=1)
        log("Pulsante FISICO: Volume +", "debug")
    except Exception as e:
        log(f"Errore nell'aumento del volume: {e}", "warning")

def action_volume_down():
    try:
        r = requests.get(f"{API_BASE}/volume", timeout=1)
        vol = r.json().get("volume", 60)
        # Lo abbassiamo di 5
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

        # Assegnazione Pressione Lunga (Hold)
        btn_next.when_held = action_volume_up
        btn_prev.when_held = action_volume_down
        btn_power.when_held = action_power_hold
        
    except Exception as e:
        log(f"Impossibile inizializzare i pulsanti: {e}", "error")

