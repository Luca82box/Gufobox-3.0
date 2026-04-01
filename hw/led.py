import eventlet
from core.state import led_runtime, bus
from core.utils import log

try:
    from rpi_ws281x import Adafruit_NeoPixel, Color
except ImportError:
    Adafruit_NeoPixel = None
    Color = None

# =========================================================
# CONFIGURAZIONE STRISCIA LED WS2813
# =========================================================
LED_COUNT      = 12      # Numero di LED nella tua striscia (modifica se necessario)
LED_PIN        = 12      # Pin PWM che hai scelto (ottimo per evitare conflitti I2S)
LED_FREQ_HZ    = 800000  # Frequenza del segnale LED (solitamente 800khz)
LED_DMA        = 10      # Canale DMA da usare per generare il segnale
LED_BRIGHTNESS = 255     # Luminosità massima (0-255)
LED_INVERT     = False   # True se usi un transistor NPN per traslare il livello logico a 5V
LED_CHANNEL    = 0       # Canale PWM (0 per GPIO12)

strip = None

def init_leds():
    global strip
    if not Adafruit_NeoPixel:
        log("Libreria rpi_ws281x non trovata. LED disabilitati.", "error")
        return

    try:
        strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
        strip.begin()
        log("Striscia LED WS2813 inizializzata sul GPIO12", "info")
        
        # Avviamo il thread in background che gestisce le animazioni
        eventlet.spawn(_led_worker)
    except Exception as e:
        log(f"Errore hardware LED: {e}. (Ricorda che rpi_ws281x richiede i permessi di root/sudo)", "error")

# =========================================================
# EFFETTI VISIVI
# =========================================================
def set_all_color(color):
    """Imposta tutti i LED su un colore specifico"""
    if not strip: return
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
    strip.show()

def _led_worker():
    """Thread in background che legge 'led_runtime' e disegna gli effetti"""
    if not strip: return
    
    step = 0
    while True:
        # 1. Controllo master (Se i LED sono disabilitati dal genitore)
        if not led_runtime.get("master_enabled", True):
            set_all_color(Color(0, 0, 0)) # Spegni tutto
            eventlet.sleep(1)
            continue
            
        effect = led_runtime.get("current_effect", "solid")
        
        # 2. Gestione degli Effetti
        if effect == "solid":
            # Colore fisso (es. blu rilassante)
            set_all_color(Color(0, 0, 255))
            eventlet.sleep(1)
            
        elif effect == "breathing":
            # Effetto "Respiro" (aumenta e diminuisce la luminosità)
            brightness = int((math.sin(step / 10.0) + 1.0) * 127.0) # Oscilla tra 0 e 254
            strip.setBrightness(brightness)
            set_all_color(Color(0, 255, 0)) # Verde
            strip.show()
            step += 1
            eventlet.sleep(0.05)
            
        elif effect == "rainbow":
            # Crea un arcobaleno che scorre
            for i in range(strip.numPixels()):
                pixel_index = (i * 256 // strip.numPixels()) + step
                strip.setPixelColor(i, wheel(pixel_index & 255))
            strip.show()
            step += 5
            eventlet.sleep(0.05)
            
        else:
            set_all_color(Color(0, 0, 0))
            eventlet.sleep(1)

def wheel(pos):
    """Genera colori arcobaleno fluidi da 0 a 255"""
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)

