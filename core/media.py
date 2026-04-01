import subprocess
import threading
import eventlet

from core.state import media_runtime, bus
from core.utils import log

# Lock di sicurezza per evitare che due thread modifichino il player contemporaneamente
player_lock = threading.Lock()
player_proc = None

def build_mpv_command(target, mode):
    """Costruisce il comando per il terminale in base al tipo di file"""
    cmd = ["mpv", "--really-quiet", "--force-window=no"]
    
    if mode == "video_hdmi":
        cmd += ["--fs", "--no-border"]
    elif mode == "audio_only":
        cmd += ["--no-video"]
        
    cmd.append(target)
    return cmd

def start_player(target, mode="audio_only"):
    """Ferma eventuali riproduzioni in corso e avvia il nuovo file"""
    global player_proc
    
    # Ferma sempre prima di far partire qualcosa di nuovo
    stop_player()
    
    cmd = build_mpv_command(target, mode)
    
    # Avvia MPV in background
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    with player_lock:
        player_proc = proc
        
    # Aggiorna lo stato globale
    media_runtime["player_running"] = True
    media_runtime["player_mode"] = mode
    
    # Segnala all'EventBus che deve salvare su SD e avvisare il frontend
    bus.mark_dirty("media")
    bus.request_emit("public")
    
    log(f"▶️ Player avviato: {target} (Modo: {mode})", "info")
    return True, "ok"

def stop_player():
    """Ferma il player in modo sicuro e pulito"""
    global player_proc
    
    with player_lock:
        proc = player_proc
        player_proc = None
        
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=2) # Aspetta 2 secondi per chiudersi con grazia...
        except Exception:
            proc.kill() # ...altrimenti lo uccide forzatamente
            
    # Aggiorna lo stato globale solo se stava suonando
    if media_runtime.get("player_running"):
        media_runtime["player_running"] = False
        media_runtime["player_mode"] = "idle"
        
        bus.mark_dirty("media")
        bus.request_emit("public")
        log("⏹️ Player fermato manualmente", "info")

def _player_watchdog_loop():
    """
    Questo è il nuovo Watchdog ad Altissima Efficienza (0% CPU).
    Attende silenziosamente che il processo MPV termini da solo (es. fine canzone).
    """
    global player_proc
    while True:
        eventlet.sleep(1) # Pausa leggera per respirare
        
        proc = player_proc
        if proc is not None:
            try:
                # proc.wait() mette in pausa QUESTO thread finché MPV non finisce.
                # Non consuma CPU mentre aspetta.
                proc.wait() 
                
                # Se il player_proc è ancora uguale a proc, significa che la canzone
                # è finita naturalmente (e non che l'utente ha premuto STOP).
                if player_proc == proc:
                    log("✅ Riproduzione terminata naturalmente.", "info")
                    media_runtime["player_running"] = False
                    media_runtime["player_mode"] = "idle"
                    
                    bus.mark_dirty("media")
                    bus.request_emit("public")
                    
                    # Rimuoviamo il processo zombie
                    player_proc = None
            except Exception as e:
                log(f"Errore nel watchdog del player: {e}", "warning")

def init_media_workers():
    """Chiamata dal main.py per avviare il Watchdog in background"""
    eventlet.spawn(_player_watchdog_loop)

