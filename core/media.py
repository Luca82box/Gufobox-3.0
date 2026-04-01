import subprocess
import threading
import socket
import json
import eventlet

from core.state import media_runtime, bus
from core.utils import log

# Lock di sicurezza per evitare che due thread modifichino il player contemporaneamente
player_lock = threading.Lock()
player_proc = None

# Percorso del socket IPC di MPV per il controllo in tempo reale
MPV_IPC_SOCKET = "/tmp/gufobox-mpv.sock"

# Tracciamo l'rfid_uid e il target correnti per il Smart Resume
_current_rfid_uid = None
_current_target = None

def build_mpv_command(target, mode):
    """Costruisce il comando per il terminale in base al tipo di file"""
    cmd = [
        "mpv",
        "--really-quiet",
        "--force-window=no",
        f"--input-ipc-server={MPV_IPC_SOCKET}",  # Abilita il controllo via socket IPC
    ]

    if mode == "video_hdmi":
        cmd += ["--fs", "--no-border"]
    elif mode == "audio_only":
        cmd += ["--no-video"]

    cmd.append(target)
    return cmd

# Timeout per la comunicazione IPC con MPV
MPV_IPC_TIMEOUT = 2

def send_mpv_command(command_args):
    """
    Invia un comando JSON al socket IPC di MPV.
    command_args: lista con il nome del comando e i parametri, es. ["playlist-next"]
    Ritorna la risposta JSON di MPV, o None in caso di errore.
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(MPV_IPC_TIMEOUT)
        sock.connect(MPV_IPC_SOCKET)
        msg = json.dumps({"command": command_args}) + "\n"
        sock.sendall(msg.encode("utf-8"))
        # Legge la risposta riga per riga (MPV termina ogni risposta con \n)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        sock.close()
        return json.loads(buf.split(b"\n")[0].decode("utf-8"))
    except Exception as e:
        log(f"Errore comunicazione IPC MPV: {e}", "warning")
        return None

def _save_resume_if_needed():
    """
    Legge la posizione corrente da MPV via IPC e la salva nel database.
    Chiamata prima di fermare la riproduzione o quando finisce naturalmente.
    """
    global _current_rfid_uid, _current_target
    if not _current_rfid_uid or not _current_target:
        return
    try:
        response = send_mpv_command(["get_property", "time-pos"])
        if response and response.get("error") == "success":
            position = response.get("data", 0) or 0
            if position > 0:
                from core.database import save_resume_position
                save_resume_position(_current_rfid_uid, _current_target, int(position))
                log(f"🔖 Smart Resume salvato: {int(position)}s per statuina {_current_rfid_uid}", "info")
    except Exception as e:
        log(f"Impossibile salvare posizione resume: {e}", "warning")

def start_player(target, mode="audio_only", rfid_uid=None):
    """Ferma eventuali riproduzioni in corso e avvia il nuovo file"""
    global player_proc, _current_rfid_uid, _current_target

    # Ferma sempre prima di far partire qualcosa di nuovo
    stop_player()

    cmd = build_mpv_command(target, mode)

    # Smart Resume: se abbiamo un rfid_uid, riprendiamo da dove eravamo
    if rfid_uid:
        from core.database import get_resume_position
        resume = get_resume_position(rfid_uid)
        if resume and resume.get("target") == target and resume.get("position", 0) > 0:
            cmd.insert(-1, f"--start=+{resume['position']}")
            log(f"🔖 Smart Resume: ripresa da {resume['position']}s per statuina {rfid_uid}", "info")

    # Traccia statuina e file correnti per il salvataggio automatico della posizione
    _current_rfid_uid = rfid_uid
    _current_target = target

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
    global player_proc, _current_rfid_uid, _current_target

    # Salva la posizione prima di fermarsi (Smart Resume)
    _save_resume_if_needed()

    with player_lock:
        proc = player_proc
        player_proc = None

    # Azzera il tracciamento corrente
    _current_rfid_uid = None
    _current_target = None

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
    global player_proc, _current_rfid_uid, _current_target
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

                    # Quando il file termina naturalmente azzeriamo il resume per quell'uid,
                    # così la prossima riproduzione riparte dall'inizio invece che dalla fine.
                    if _current_rfid_uid:
                        try:
                            from core.database import clear_resume_position
                            clear_resume_position(_current_rfid_uid)
                            log(f"🔖 Resume azzerato per statuina {_current_rfid_uid} (fine naturale)", "info")
                        except Exception as e:
                            log(f"Impossibile azzerare resume: {e}", "warning")

                    media_runtime["player_running"] = False
                    media_runtime["player_mode"] = "idle"

                    bus.mark_dirty("media")
                    bus.request_emit("public")

                    # Azzera lo stato di tracciamento e rimuove il processo zombie
                    _current_rfid_uid = None
                    _current_target = None
                    player_proc = None
            except Exception as e:
                log(f"Errore nel watchdog del player: {e}", "warning")

def init_media_workers():
    """Chiamata dal main.py per avviare il Watchdog in background"""
    eventlet.spawn(_player_watchdog_loop)

