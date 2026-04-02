import os
import time
import hashlib
import smbus2
import eventlet
from core.state import state, bus
from core.utils import log
from core.media import start_player
from config import AI_TTS_CACHE_DIR, OPENAI_API_KEY

# Indirizzo I2C standard del MAX17048
MAX17048_ADDRESS = 0x36
REG_VCELL = 0x02
REG_SOC = 0x04
REG_CRATE = 0x16  # CRATE register: rate of change (positive = charging)

def read_battery_max17048():
    try:
        with smbus2.SMBus(1) as i2c_bus:
            # Legge la percentuale di carica (State of Charge)
            soc_data = i2c_bus.read_i2c_block_data(MAX17048_ADDRESS, REG_SOC, 2)
            percent = soc_data[0] + (soc_data[1] / 256.0)
            
            # Legge il voltaggio (VCELL)
            vcell_data = i2c_bus.read_i2c_block_data(MAX17048_ADDRESS, REG_VCELL, 2)
            voltage = (vcell_data[0] << 4 | vcell_data[1] >> 4) * 0.00125
            
            # Legge il CRATE (rate of change): positivo → in carica, negativo → in scarica
            crate = None
            try:
                crate_data = i2c_bus.read_i2c_block_data(MAX17048_ADDRESS, REG_CRATE, 2)
                raw = (crate_data[0] << 8) | crate_data[1]
                # CRATE è un valore signed a 16 bit (complemento a 2), in unità di 0.208%/h
                if raw >= 0x8000:
                    raw -= 0x10000
                crate = raw * 0.208  # %/h
            except Exception:
                pass

            return round(percent, 1), round(voltage, 2), crate
    except Exception as e:
        log(f"Errore lettura MAX17048: {e}", "warning")
        return None, None, None

def play_ai_notification(text):
    """Genera e riproduce una notifica audio simpatica in stile gufetto"""
    try:
        from openai import OpenAI
    except ImportError:
        log(f"Notifica vocale (solo testo): {text}", "info")
        return

    api_key = OPENAI_API_KEY
    if not api_key:
        log(f"Notifica vocale (no API key): {text}", "info")
        return

    try:
        client = OpenAI(api_key=api_key)
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        audio_path = os.path.join(AI_TTS_CACHE_DIR, f"notif_{text_hash}.mp3")

        if not os.path.exists(audio_path):
            tts_response = client.audio.speech.create(
                model="tts-1",
                voice="nova",
                input=text
            )
            tts_response.stream_to_file(audio_path)

        start_player(audio_path, mode="audio_only")
    except Exception as e:
        log(f"Errore notifica AI vocale: {e}", "warning")

def _battery_watchdog():
    from core.utils import is_shutdown_requested
    alert_20_played = False
    alert_10_played = False
    charging_notif_played = False
    was_charging = False

    while not is_shutdown_requested():
        percent, voltage, crate = read_battery_max17048()
        
        if percent is not None:
            # Determina se in carica dal registro CRATE (positivo = in carica)
            # Fallback: se CRATE non disponibile, usa tendenza voltaggio
            charging = False
            if crate is not None:
                charging = crate > 0.5  # soglia minima per evitare rumore
            
            # Determina lo stato semantico della batteria
            if charging:
                status = "charging"
            elif percent <= 10:
                status = "critical"
            elif percent <= 20:
                status = "low"
            else:
                status = "normal"

            # Aggiorna state["battery"] come dizionario strutturato
            state["battery"] = {
                "percent": percent,
                "voltage": voltage,
                "charging": charging,
                "status": status,
                "updated_ts": int(time.time()),
            }
            bus.mark_dirty("state")
            bus.request_emit("public")

            # Notifica quando inizia la ricarica (con cooldown)
            if charging and not was_charging and not charging_notif_played:
                play_ai_notification("Uhuu! Mi sto ricaricando, grazie!")
                bus.emit_notification("Batteria in ricarica 🔌", "info")
                charging_notif_played = True
            elif not charging:
                charging_notif_played = False

            was_charging = charging

            # Notifiche batteria quasi scarica e scarica
            if not charging:
                if 10 < percent <= 20 and not alert_20_played:
                    play_ai_notification("Uhuu! La mia pancina brontola, la batteria è al 20 percento! Attaccami alla corrente.")
                    bus.emit_notification("Batteria al 20%", "warning")
                    alert_20_played = True
                    
                elif percent <= 10 and not alert_10_played:
                    play_ai_notification("Uhuu! Sto per addormentarmi... batteria quasi finita! Mettimi in carica per favore.")
                    bus.emit_notification("Batteria CRITICA!", "error")
                    alert_10_played = True
                    
                    # Sotto il 5% forza lo standby per non rovinare le celle
                    if percent <= 5:
                        from core.hardware import perform_standby
                        perform_standby()

            # Resetta gli alert se la batteria è tornata su (in carica o > 25%)
            if charging or percent > 25:
                alert_20_played = False
                alert_10_played = False

        eventlet.sleep(60) # Controlla ogni minuto

def init_battery():
    eventlet.spawn(_battery_watchdog)

