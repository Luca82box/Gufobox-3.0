import smbus2
import eventlet
from core.state import state, bus
from core.utils import log
from core.media import start_player
from api.ai import ai_generate_tts_openai

# Indirizzo I2C standard del MAX17048
MAX17048_ADDRESS = 0x36
REG_VCELL = 0x02
REG_SOC = 0x04

def read_battery_max17048():
    try:
        with smbus2.SMBus(1) as i2c_bus:
            # Legge la percentuale di carica (State of Charge)
            soc_data = i2c_bus.read_i2c_block_data(MAX17048_ADDRESS, REG_SOC, 2)
            percent = soc_data[0] + (soc_data[1] / 256.0)
            
            # Legge il voltaggio (VCELL)
            vcell_data = i2c_bus.read_i2c_block_data(MAX17048_ADDRESS, REG_VCELL, 2)
            voltage = (vcell_data[0] << 4 | vcell_data[1] >> 4) * 0.00125
            
            return round(percent, 1), round(voltage, 2)
    except Exception as e:
        log(f"Errore lettura MAX17048: {e}", "warning")
        return None, None

def play_ai_notification(text):
    """Genera e riproduce una notifica audio simpatica in stile gufetto"""
    try:
        # Usa il TTS di OpenAI per creare l'audio
        audio_path = ai_generate_tts_openai(text, "nova")
        if audio_path:
            start_player(audio_path, mode="audio_only")
    except Exception as e:
        log(f"Errore notifica AI: {e}", "error")

def _battery_watchdog():
    alert_20_played = False
    alert_10_played = False

    while True:
        percent, voltage = read_battery_max17048()
        
        if percent is not None:
            state["battery_percent"] = percent
            state["battery_voltage"] = voltage
            bus.mark_dirty("state")
            bus.request_emit("public")

            # Notifiche batteria quasi scarica e scarica (#16)
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

            # Resetta gli alert se in carica
            elif percent > 25:
                alert_20_played = False
                alert_10_played = False

        eventlet.sleep(60) # Controlla ogni minuto

def init_battery():
    eventlet.spawn(_battery_watchdog)

