import os
import eventlet
from gpiozero import DigitalOutputDevice
from datetime import datetime, timedelta

from core.state import media_runtime, alarms_list, bus, now_ts
from core.utils import log, run_cmd

# Configurazione Pin Amplificatore (dalla Scheda Tecnica 2026)
PIN_AMP_TRIGGER = 20  
PIN_AMP_MUTE    = 26  

try:
    amp_trigger = DigitalOutputDevice(PIN_AMP_TRIGGER, initial_value=False)
    amp_mute = DigitalOutputDevice(PIN_AMP_MUTE, initial_value=True)
except Exception:
    amp_trigger, amp_mute = None, None

def amp_on():
    if amp_trigger:
        amp_trigger.on()
        eventlet.sleep(0.1) # Anti-pop delay
        amp_mute.off()

def amp_off():
    if amp_mute:
        amp_mute.on()
        eventlet.sleep(0.1)
        amp_trigger.off()

def perform_standby():
    """Mette la GufoBox in stato di minima energia reale (#6)"""
    from core.media import stop_player 
    from core.hw_battery import play_ai_notification
    
    bus.emit_notification("GufoBox in Standby profondo... 🌙", "warning")
    play_ai_notification("Uhuu, che sonno! Faccio un pisolino. A dopo!")
    eventlet.sleep(3) # Attende che l'audio finisca
    
    stop_player()
    amp_off() # Spegne fisicamente il PAM8406 (#5)
    
    # 1. Disabilita Rete e Bluetooth
    log("Disabilitazione radio...", "info")
    run_cmd(["sudo", "rfkill", "block", "all"]) 
    
    # 2. Spegne l'alimentazione al chip USB (risparmio drastico)
    run_cmd(["sudo", "sh", "-c", "echo '1-1' > /sys/bus/usb/drivers/usb/unbind"])
    
    # 3. Spegne l'uscita HDMI 
    run_cmd(["sudo", "vcgencmd", "display_power", "0"])

    # 4. Imposta la CPU al minimo sindacale (powersave governor)
    run_cmd(["sudo", "cpufreq-set", "-g", "powersave"])
    
    log("Deep Standby mode engaged.", "info")

def wake_from_standby():
    """Risveglia il sistema (da chiamare col pulsante Power)"""
    run_cmd(["sudo", "rfkill", "unblock", "all"])
    run_cmd(["sudo", "sh", "-c", "echo '1-1' > /sys/bus/usb/drivers/usb/bind"])
    run_cmd(["sudo", "cpufreq-set", "-g", "ondemand"])
    from core.hw_battery import play_ai_notification
    play_ai_notification("Uhuu! Sono sveglio e pronto a giocare!")

