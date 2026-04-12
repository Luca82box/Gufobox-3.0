# IMPORTANTE (eventlet): usare SEMPRE eventlet.sleep() nei loop di questo
# worker — mai time.sleep(). time.sleep() blocca il thread eventlet e congela
# l'intera applicazione cooperativa.

import math
import random
import eventlet
from core.state import led_runtime, bus
from core.utils import log
from config import LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_BRIGHTNESS, LED_INVERT, LED_CHANNEL

try:
    from rpi_ws281x import Adafruit_NeoPixel, Color
except ImportError:
    Adafruit_NeoPixel = None
    Color = None

# =========================================================
# CONFIGURAZIONE STRISCIA LED WS2813
# =========================================================
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

def _hex_to_color(hex_str):
    """Converte un colore hex (#rrggbb) in un oggetto Color NeoPixel."""
    if Color is None:
        return 0
    try:
        h = hex_str.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return Color(r, g, b)
    except Exception as e:
        log(f"Errore parsing colore hex '{hex_str}': {e}. Uso blu di default.", "warning")
        return Color(0, 0, 255)  # Fallback: blu


def _led_worker():
    """Thread in background che legge 'led_runtime' e disegna gli effetti"""
    if not strip: return
    from core.utils import is_shutdown_requested
    
    step = 0
    while not is_shutdown_requested():
        # 1. Controllo master (Se i LED sono disabilitati)
        # Leggi prima da 'applied' (nuovo schema), poi da campi legacy
        applied = led_runtime.get("applied", {})
        master_enabled = applied.get("enabled", led_runtime.get("master_enabled", True))
        if not master_enabled:
            set_all_color(Color(0, 0, 0)) # Spegni tutto
            eventlet.sleep(1)
            continue
            
        effect = applied.get("effect_id") or led_runtime.get("current_effect", "solid")
        color_hex = applied.get("color") or led_runtime.get("master_color", "#0000ff")
        speed = max(1, applied.get("speed") if applied.get("speed") is not None
                    else led_runtime.get("master_speed", 30))
        brightness_pct = (applied.get("brightness") if applied.get("brightness") is not None
                          else led_runtime.get("master_brightness", 70))
        strip.setBrightness(int(brightness_pct * 255 / 100))

        # Calcola sleep in base alla velocità (1-100 -> 0.01-1s)
        sleep_time = max(0.01, (101 - speed) / 100.0)
        
        # 2. Gestione degli Effetti
        if effect == "off":
            set_all_color(Color(0, 0, 0))
            eventlet.sleep(1)

        elif effect == "solid":
            set_all_color(_hex_to_color(color_hex))
            eventlet.sleep(1)
            
        elif effect == "breathing":
            max_b = int(brightness_pct * 255 / 100)
            brightness = int((math.sin(step / 10.0) + 1.0) / 2.0 * max_b)
            strip.setBrightness(brightness)
            set_all_color(_hex_to_color(color_hex))
            strip.show()
            step += 1
            step = step % 100000
            eventlet.sleep(sleep_time)

        elif effect == "blink":
            set_all_color(_hex_to_color(color_hex))
            eventlet.sleep(sleep_time)
            set_all_color(Color(0, 0, 0))
            eventlet.sleep(sleep_time)
            
        elif effect == "rainbow":
            for i in range(strip.numPixels()):
                pixel_index = (i * 256 // strip.numPixels()) + step
                strip.setPixelColor(i, wheel(pixel_index & 255))
            strip.show()
            step += 5
            step = step % 100000
            eventlet.sleep(sleep_time)

        elif effect == "pulse":
            c = _hex_to_color(color_hex)
            set_all_color(c)
            strip.show()
            eventlet.sleep(sleep_time * 0.3)
            set_all_color(Color(0, 0, 0))
            strip.show()
            eventlet.sleep(sleep_time * 0.7)

        elif effect == "theater_chase":
            # TODO: per carichi LED elevati (strisce >100 pixel) valuta di
            # spostare theater_chase, fire, twinkle in un multiprocessing.Process
            # separato comunicando via Queue, così da non saturare l'hub eventlet.
            for q in range(3):
                for i in range(0, strip.numPixels(), 3):
                    if i + q < strip.numPixels():
                        strip.setPixelColor(i + q, _hex_to_color(color_hex))
                strip.show()
                eventlet.sleep(sleep_time)
                for i in range(0, strip.numPixels(), 3):
                    if i + q < strip.numPixels():
                        strip.setPixelColor(i + q, Color(0, 0, 0))
            # Yield dopo il clear così l'hub eventlet rimane reattivo
            eventlet.sleep(0.01)

        elif effect == "bounce":
            pos = step % (strip.numPixels() * 2 - 2)
            if pos >= strip.numPixels():
                pos = (strip.numPixels() * 2 - 2) - pos
            set_all_color(Color(0, 0, 0))
            strip.setPixelColor(pos, _hex_to_color(color_hex))
            strip.show()
            step += 1
            step = step % 100000
            eventlet.sleep(sleep_time)

        elif effect == "twinkle":
            set_all_color(Color(0, 0, 0))
            for _ in range(max(1, strip.numPixels() // 3)):
                idx = random.randint(0, strip.numPixels() - 1)
                strip.setPixelColor(idx, _hex_to_color(color_hex))
            strip.show()
            step += 1
            step = step % 100000
            eventlet.sleep(sleep_time)

        elif effect == "fire":
            for i in range(strip.numPixels()):
                flicker = random.randint(0, 80)
                r = max(0, 226 - flicker)
                g = max(0, 121 - flicker)
                b = max(0, 35 - flicker // 2)
                strip.setPixelColor(i, Color(r, g, b))
            strip.show()
            step += 1
            step = step % 100000
            eventlet.sleep(sleep_time * 0.5)

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

