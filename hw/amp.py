from gpiozero import DigitalOutputDevice
import eventlet
from core.utils import log

# =========================================================
# CONFIGURAZIONE PIN (Dalla tua scheda tecnica)
# =========================================================
PIN_AMP_TRIGGER = 20  # Accende/Spegne l'alimentazione all'amplificatore
PIN_AMP_MUTE    = 26  # Mette in muto il PAM8406

try:
    # Inizializziamo i pin (di default li teniamo spenti/mutati)
    amp_trigger = DigitalOutputDevice(PIN_AMP_TRIGGER, initial_value=False)
    amp_mute = DigitalOutputDevice(PIN_AMP_MUTE, initial_value=True) # Assumendo che True = Mute (Active High/Low dipende dal cablaggio)
except Exception as e:
    log(f"Errore inizializzazione pin Amplificatore: {e}", "error")
    amp_trigger = None
    amp_mute = None

def amp_on():
    """Accende l'amplificatore e toglie il mute in modo morbido (anti-pop)"""
    if not amp_trigger: return
    
    log("🔊 Accensione Amplificatore...", "debug")
    amp_trigger.on()       # Dà corrente
    eventlet.sleep(0.1)    # Aspetta 100ms per stabilizzare l'alimentazione ed evitare il "POP"
    amp_mute.off()         # Toglie il mute

def amp_off():
    """Mette in muto e poi toglie l'alimentazione"""
    if not amp_trigger: return
    
    log("🔇 Spegnimento Amplificatore...", "debug")
    amp_mute.on()          # Mette in muto istantaneamente
    eventlet.sleep(0.1)    # Aspetta 100ms
    amp_trigger.off()      # Toglie corrente

