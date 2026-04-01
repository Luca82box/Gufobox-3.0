import os
import eventlet
from datetime import datetime, timedelta

from core.state import media_runtime, alarms_list, bus, now_ts
from core.utils import log, run_cmd
from hw.amp import amp_on, amp_off

def perform_standby():
    """Mette la GufoBox in stato di minima energia reale (#6)"""
    from core.media import stop_player 
    from hw.battery import play_ai_notification
    
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

def init_hardware_workers():
    """Avvia i worker hardware in background"""
    log("Avvio worker hardware (Sleep Timer)...", "info")
    eventlet.spawn(_sleep_timer_worker)

