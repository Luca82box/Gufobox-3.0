import os
import subprocess
import threading
import socket
import json
import eventlet

from core.state import media_runtime, bus
from core.utils import log
from config import MEDIA_EXTENSIONS

# Lock di sicurezza per evitare che due thread modifichino il player contemporaneamente
player_lock = threading.Lock()
player_proc = None

# Percorso del socket IPC di MPV per il controllo in tempo reale
MPV_IPC_SOCKET = "/tmp/gufobox-mpv.sock"

# Tracciamo l'rfid_uid e il target correnti per il Smart Resume
_current_rfid_uid = None
_current_target = None
_current_playlist_index = 0


# =========================================================
# PLAYLIST BUILDER
# =========================================================
def build_playlist(folder):
    """Costruisce una lista ordinata di file media da una cartella."""
    try:
        real_folder = os.path.realpath(folder)
        if not os.path.isdir(real_folder):
            return []
        files = sorted(
            os.path.join(real_folder, f)
            for f in os.listdir(real_folder)
            if os.path.splitext(f)[1].lower() in MEDIA_EXTENSIONS
        )
        return files
    except Exception as e:
        log(f"Errore build_playlist({folder}): {e}", "warning")
        return []

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
    global _current_rfid_uid, _current_target, _current_playlist_index
    if not _current_rfid_uid or not _current_target:
        return
    try:
        response = send_mpv_command(["get_property", "time-pos"])
        if response and response.get("error") == "success":
            position = response.get("data", 0) or 0
            if position > 0:
                from core.database import save_resume_position
                save_resume_position(
                    _current_rfid_uid,
                    _current_target,
                    int(position),
                    playlist_index=_current_playlist_index,
                )
                log(f"🔖 Smart Resume salvato: {int(position)}s idx={_current_playlist_index} per statuina {_current_rfid_uid}", "info")
    except Exception as e:
        log(f"Impossibile salvare posizione resume: {e}", "warning")

def start_player(target, mode="audio_only", rfid_uid=None, playlist_index=0,
                 profile_name=None, profile_mode=None, volume=None):
    """Ferma eventuali riproduzioni in corso e avvia il nuovo file"""
    global player_proc, _current_rfid_uid, _current_target, _current_playlist_index

    # Ferma sempre prima di far partire qualcosa di nuovo
    stop_player()

    cmd = build_mpv_command(target, mode)

    # Smart Resume: se abbiamo un rfid_uid, riprendiamo da dove eravamo
    resume_info = None
    if rfid_uid:
        from core.database import get_resume_position
        resume = get_resume_position(rfid_uid)
        if resume and resume.get("target") == target and resume.get("position", 0) > 0:
            # Usa l'indice playlist salvato se non ne viene fornito uno esplicito
            if playlist_index == 0 and resume.get("playlist_index", 0) > 0:
                playlist_index = resume["playlist_index"]
            cmd.insert(-1, f"--start=+{resume['position']}")
            resume_info = resume
            log(f"🔖 Smart Resume: ripresa da {resume['position']}s idx={playlist_index} per statuina {rfid_uid}", "info")

    # Traccia statuina e file correnti per il salvataggio automatico della posizione
    _current_rfid_uid = rfid_uid
    _current_target = target
    _current_playlist_index = playlist_index

    # Applica volume se specificato
    if volume is not None:
        try:
            from core.utils import run_cmd
            vol = max(0, min(100, int(volume)))
            run_cmd(["amixer", "sset", "Master", f"{vol}%"])
            media_runtime["current_volume"] = vol
        except Exception as e:
            log(f"Errore impostazione volume: {e}", "warning")

    # Avvia MPV in background
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with player_lock:
        player_proc = proc

    # Aggiorna lo stato globale (campi base + PR2 estesi)
    media_runtime["player_running"] = True
    media_runtime["player_mode"] = mode
    media_runtime["current_file"] = target
    media_runtime["current_rfid_uid"] = rfid_uid
    media_runtime["resume_position"] = resume_info
    # Campi PR2
    media_runtime["current_rfid"] = rfid_uid
    media_runtime["current_profile_name"] = profile_name
    media_runtime["current_mode"] = profile_mode or mode
    media_runtime["current_media_path"] = target
    media_runtime["playlist_index"] = playlist_index

    # Segnala all'EventBus che deve salvare su SD e avvisare il frontend
    bus.mark_dirty("media")
    bus.request_emit("public")

    log(f"▶️ Player avviato: {target} (Modo: {mode})", "info")
    return True, "ok"

def stop_player():
    """Ferma il player in modo sicuro e pulito"""
    global player_proc, _current_rfid_uid, _current_target, _current_playlist_index

    # Salva la posizione prima di fermarsi (Smart Resume)
    _save_resume_if_needed()

    with player_lock:
        proc = player_proc
        player_proc = None

    # Azzera il tracciamento corrente
    _current_rfid_uid = None
    _current_target = None
    _current_playlist_index = 0

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
        media_runtime["current_file"] = None
        media_runtime["current_rfid_uid"] = None
        media_runtime["current_rfid"] = None
        media_runtime["current_profile_name"] = None
        media_runtime["current_mode"] = "idle"
        media_runtime["current_media_path"] = None
        media_runtime["current_playlist"] = []
        media_runtime["playlist_index"] = 0

        bus.mark_dirty("media")
        bus.request_emit("public")
        log("⏹️ Player fermato manualmente", "info")

def _player_watchdog_loop():
    """
    Questo è il nuovo Watchdog ad Altissima Efficienza (0% CPU).
    Attende silenziosamente che il processo MPV termini da solo (es. fine canzone).
    """
    from core.utils import is_shutdown_requested
    global player_proc, _current_rfid_uid, _current_target
    while not is_shutdown_requested():
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
                    media_runtime["current_file"] = None
                    media_runtime["current_rfid_uid"] = None
                    media_runtime["current_rfid"] = None
                    media_runtime["current_profile_name"] = None
                    media_runtime["current_mode"] = "idle"
                    media_runtime["current_media_path"] = None
                    media_runtime["current_playlist"] = []
                    media_runtime["playlist_index"] = 0

                    bus.mark_dirty("media")
                    bus.request_emit("public")

                    # Azzera lo stato di tracciamento e rimuove il processo zombie
                    _current_rfid_uid = None
                    _current_target = None
                    _current_playlist_index = 0
                    player_proc = None
            except Exception as e:
                log(f"Errore nel watchdog del player: {e}", "warning")

def init_media_workers():
    """Chiamata dal main.py per avviare il Watchdog in background"""
    eventlet.spawn(_player_watchdog_loop)

