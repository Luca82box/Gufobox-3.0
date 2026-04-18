import os
import time
import subprocess
import threading  # Nota: con eventlet.monkey_patch() in main.py, threading.Lock diventa
                  # green-thread-safe automaticamente. Senza monkey_patch (alcuni test),
                  # i lock funzionano comunque in modo standard.
import socket
import json
import eventlet

from core.state import media_runtime, bus
from core.utils import log
from config import MEDIA_EXTENSIONS

# Socket IPC per la comunicazione bidirezionale con MPV
MPV_IPC_SOCKET = "/tmp/mpv-gufobox-socket"

# player_lock protegge atomicamente player_proc E tutte le variabili di
# tracciamento sessione (_current_rfid_uid, _current_target,
# _current_playlist_index, _session_start_ts).
# In questo modo il watchdog non può azzerare _session_start_ts di una nuova
# canzone mentre start_player sta già impostando la sessione successiva.
player_lock = threading.Lock()
player_proc = None

# Variabili di tracciamento sessione — accedere SEMPRE sotto player_lock
_current_rfid_uid = None
_current_target = None
_current_playlist_index = 0
_session_start_ts = None  # Timestamp di inizio sessione per le statistiche

# Lock separato per le modifiche batch a media_runtime (evita letture inconsistenti
# dall'EventBus mentre stiamo aggiornando più campi del dict in sequenza).
_media_runtime_lock = threading.Lock()


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
    Acquisisce un snapshot delle variabili di sessione sotto player_lock,
    poi esegue I/O (IPC + DB) fuori dal lock per non bloccare altri thread.
    """
    # Snapshot atomico delle variabili di sessione sotto player_lock
    with player_lock:
        uid = _current_rfid_uid
        target = _current_target
        playlist_idx = _current_playlist_index

    if not uid or not target:
        return
    try:
        response = send_mpv_command(["get_property", "time-pos"])
        if response and response.get("error") == "success":
            position = response.get("data", 0) or 0
            if position > 0:
                from core.database import save_resume_position
                save_resume_position(uid, target, int(position), playlist_index=playlist_idx)
                log(f"🔖 Smart Resume salvato: {int(position)}s idx={playlist_idx} per statuina {uid}", "info")
    except Exception as e:
        log(f"Impossibile salvare posizione resume: {e}", "warning")

def start_player(target, mode="audio_only", rfid_uid=None, playlist_index=0,
                 profile_name=None, profile_mode=None, volume=None):
    """Ferma eventuali riproduzioni in corso e avvia il nuovo file"""
    global player_proc, _current_rfid_uid, _current_target, _current_playlist_index, _session_start_ts

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

    # Aggiorna player_proc E le variabili di sessione in modo atomico.
    # È fondamentale che player_lock copra anche _current_rfid_uid/_session_start_ts
    # per evitare che il watchdog (che vede proc.wait() tornare) legga un
    # _session_start_ts già sostituito dalla nuova sessione.
    with player_lock:
        player_proc = proc
        _current_rfid_uid = rfid_uid
        _current_target = target
        _current_playlist_index = playlist_index
        _session_start_ts = time.time() if rfid_uid else None

    # Aggiorna lo stato globale in modo atomico (evita letture inconsistenti da altri thread)
    with _media_runtime_lock:
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

def _reset_media_runtime():
    """Azzera i campi media_runtime quando il player si ferma e notifica EventBus."""
    with _media_runtime_lock:
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


def stop_player():
    """Ferma il player in modo sicuro e pulito"""
    global player_proc, _current_rfid_uid, _current_target, _current_playlist_index, _session_start_ts

    # Salva la posizione prima di fermarsi (Smart Resume).
    # _save_resume_if_needed() prende il proprio snapshot sotto player_lock,
    # quindi è sicura da chiamare prima di acquisire il lock qui sotto.
    _save_resume_if_needed()

    # Sotto player_lock: leggi il processo corrente e azzera ATOMICAMENTE tutte
    # le variabili di sessione, così il watchdog non può più toccarle.
    with player_lock:
        proc = player_proc
        player_proc = None
        uid_to_log = _current_rfid_uid
        ts_to_log = _session_start_ts
        _session_start_ts = None
        _current_rfid_uid = None
        _current_target = None
        _current_playlist_index = 0

    if uid_to_log and ts_to_log is not None:
        try:
            duration = int(time.time() - ts_to_log)
            from core.database import log_listening_session
            log_listening_session(uid_to_log, duration)
        except Exception as e:
            log(f"Impossibile registrare sessione di ascolto: {e}", "warning")

    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=2)  # Aspetta 2 secondi per chiudersi con grazia...
        except Exception:
            proc.kill()  # ...altrimenti lo uccide forzatamente

    # Aggiorna lo stato globale solo se stava suonando
    if media_runtime.get("player_running"):
        _reset_media_runtime()
        log("⏹️ Player fermato manualmente", "info")

def _player_watchdog_loop():
    """
    Watchdog ad Altissima Efficienza (0% CPU).
    Attende silenziosamente che il processo MPV termini da solo (es. fine canzone).

    Protezione race condition:
      Dopo proc.wait(), acquisisce player_lock e verifica ATOMICAMENTE se
      player_proc == proc prima di leggere o azzerare qualsiasi variabile di
      sessione.  Questo impedisce che il watchdog azzeri _session_start_ts di
      una nuova canzone avviata da start_player mentre il vecchio MPV stava
      ancora terminando.
    """
    from core.utils import is_shutdown_requested
    global player_proc, _current_rfid_uid, _current_target, _current_playlist_index, _session_start_ts
    while not is_shutdown_requested():
        eventlet.sleep(1)  # Pausa leggera per respirare

        # Legge player_proc senza lock (solo anteprima per decidere se aspettare)
        proc = player_proc
        if proc is None:
            continue

        try:
            # proc.wait() mette in pausa QUESTO thread finché MPV non finisce.
            # Non consuma CPU mentre aspetta.
            proc.wait()

            # Acquisisce player_lock per verificare ATOMICAMENTE se siamo ancora
            # la sessione corrente (e non una già sostituita da start_player).
            with player_lock:
                if player_proc != proc:
                    # Un altro thread (stop_player o un nuovo start_player) ha già
                    # preso il controllo: non toccare nulla.
                    continue

                # Siamo la sessione che è appena finita naturalmente.
                # Estraiamo i dati di sessione e puliamo tutto in modo atomico.
                log("✅ Riproduzione terminata naturalmente.", "info")
                uid_ended = _current_rfid_uid
                ts_ended = _session_start_ts
                _session_start_ts = None
                _current_rfid_uid = None
                _current_target = None
                _current_playlist_index = 0
                player_proc = None

            # Ora fuori dal lock: operazioni I/O (DB) con i dati estratti sopra
            if uid_ended and ts_ended is not None:
                try:
                    duration = int(time.time() - ts_ended)
                    from core.database import log_listening_session
                    log_listening_session(uid_ended, duration)
                except Exception as e:
                    log(f"Impossibile registrare sessione di ascolto (fine naturale): {e}", "warning")

            # Quando il file termina naturalmente azzeriamo il resume per quell'uid,
            # così la prossima riproduzione riparte dall'inizio invece che dalla fine.
            if uid_ended:
                try:
                    from core.database import clear_resume_position
                    clear_resume_position(uid_ended)
                    log(f"🔖 Resume azzerato per statuina {uid_ended} (fine naturale)", "info")
                except Exception as e:
                    log(f"Impossibile azzerare resume: {e}", "warning")

            _reset_media_runtime()

        except Exception as e:
            log(f"Errore nel watchdog del player: {e}", "warning")

def _update_playback_position():
    """Interroga MPV per la posizione corrente e aggiorna media_runtime."""
    try:
        pos_resp = send_mpv_command(["get_property", "time-pos"])
        dur_resp = send_mpv_command(["get_property", "duration"])
        pause_resp = send_mpv_command(["get_property", "pause"])

        if pos_resp and pos_resp.get("error") == "success":
            media_runtime["position_sec"] = round(pos_resp.get("data", 0) or 0, 1)
        if dur_resp and dur_resp.get("error") == "success":
            media_runtime["duration_sec"] = round(dur_resp.get("data", 0) or 0, 1)
        if pause_resp and pause_resp.get("error") == "success":
            media_runtime["paused"] = bool(pause_resp.get("data", False))

        bus.request_emit("public")
    except Exception:
        pass


def _position_poll_worker():
    """Aggiorna la posizione di riproduzione ogni secondo per la progress bar del frontend."""
    from core.utils import is_shutdown_requested
    while not is_shutdown_requested():
        if media_runtime.get("player_running") and player_proc is not None:
            _update_playback_position()
        eventlet.sleep(1)


def init_media_workers():
    """Chiamata dal main.py per avviare il Watchdog in background"""
    eventlet.spawn(_player_watchdog_loop)
    eventlet.spawn(_position_poll_worker)

