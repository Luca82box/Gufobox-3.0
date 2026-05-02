"""
core/voice_recorder.py — Registrazione vocale guidata via statuina RFID.

Gestisce il flusso completo per il mode=statuina_record:
  1. Riproduce il prompt iniziale offline (Piper TTS)
  2. Riproduce il verso del gufo (SFX sintetico)
  3. Avvia la registrazione audio (arecord)
  4. Si ferma al pressione di play/pausa OPPURE allo scadere di 5 minuti
  5. Converte il file catturato in MP3 192 kbps / 44.1 kHz (ffmpeg)
  6. Salva nella cartella media/registrazioni/ con sidecar .meta.json
  7. Riproduce il messaggio di conferma offline (Piper TTS)

API pubblica:
  start_statuina_recording(rfid_code, profile_name) -> bool
  stop_statuina_recording()
  is_statuina_recording() -> bool
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone

from config import OFFLINE_FALLBACK_DIR, TMP_UPLOADS_ROOT, MEDIA_ROOT
from core.utils import log

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

# Cartella dove vengono salvate le registrazioni (stessa di api/voice.py)
RECORDINGS_DIR = os.path.join(MEDIA_ROOT, "registrazioni")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# Cartella di cache per i WAV offline del flusso statuina_record
_OFFLINE_DIR = os.path.join(OFFLINE_FALLBACK_DIR, "statuina_record")
os.makedirs(_OFFLINE_DIR, exist_ok=True)

# Durata massima registrazione (secondi)
RECORDING_MAX_SECONDS = 300  # 5 minuti

# Testi prompts
_PROMPT_START = "Ciao amico mio, registra ora la tua voce."
_PROMPT_END = (
    "Bene amico mio, ora la registrazione viene salvata, "
    "se vorrai registrare ancora ripassa la statuina."
)

# ---------------------------------------------------------------------------
# Stato condiviso (thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict = {}   # chiavi: rec_process, tmp_wav, stop_event, thread


# ---------------------------------------------------------------------------
# Helpers interni
# ---------------------------------------------------------------------------

def _get_or_gen_owl_hoot() -> str | None:
    """Restituisce il path del WAV owl_hoot, generandolo se necessario."""
    path = os.path.join(_OFFLINE_DIR, "owl_hoot.wav")
    if os.path.isfile(path):
        return path
    try:
        from core.sfx_generator import generate_sfx
        generate_sfx("owl_hoot", _OFFLINE_DIR)
        return path
    except Exception as e:
        log(f"statuina_record: impossibile generare owl_hoot SFX: {e}", "warning")
        return None


def _get_or_gen_piper_wav(text: str, cache_key: str) -> str | None:
    """Sintetizza `text` con Piper (offline) e restituisce il path WAV.
    Usa `cache_key` per il nome file nella cartella _OFFLINE_DIR."""
    path = os.path.join(_OFFLINE_DIR, f"{cache_key}.wav")
    if os.path.isfile(path):
        return path
    try:
        from api.tts import synthesize_with_piper
        import shutil
        wav = synthesize_with_piper(text)
        shutil.copy2(wav, path)
        return path
    except Exception as e:
        log(f"statuina_record: Piper TTS non disponibile per '{cache_key}': {e}", "warning")
        return None


def _play_blocking(path: str, timeout: float = 60.0) -> None:
    """Riproduce `path` con MPV in modo bloccante (aspetta la fine)."""
    if not path or not os.path.isfile(path):
        return
    try:
        subprocess.run(
            ["mpv", "--no-video", "--really-quiet", path],
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        log(f"statuina_record: riproduzione bloccante scaduta per {path}", "warning")
    except FileNotFoundError:
        log("statuina_record: mpv non trovato, salto riproduzione audio", "warning")
    except Exception as e:
        log(f"statuina_record: errore riproduzione {path}: {e}", "warning")


def _save_meta(mp3_name: str, rfid_code: str, profile_name: str) -> None:
    """Crea il sidecar .meta.json per la registrazione salvata."""
    meta = {
        "name": profile_name or mp3_name,
        "role": "bambino",
        "author": "",
        "rfid_code": rfid_code,
        "description": "Registrazione vocale statuina",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    meta_path = os.path.join(RECORDINGS_DIR, mp3_name + ".meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"statuina_record: errore scrittura metadati: {e}", "warning")


def _convert_to_mp3(tmp_wav: str, mp3_path: str) -> bool:
    """Converte tmp_wav → MP3 192 kbps / 44.1 kHz con ffmpeg.
    Ritorna True se la conversione è riuscita."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_wav,
                "-codec:a", "libmp3lame",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "1",
                mp3_path,
            ],
            timeout=120,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except FileNotFoundError:
        log("statuina_record: ffmpeg non trovato, impossibile convertire in MP3", "error")
    except subprocess.TimeoutExpired:
        log("statuina_record: ffmpeg timeout durante conversione MP3", "error")
    except Exception as e:
        log(f"statuina_record: errore conversione MP3: {e}", "error")
    return False


def _recording_thread(rfid_code: str, profile_name: str, stop_event: threading.Event) -> None:
    """Thread principale del flusso statuina_record."""
    from core.state import media_runtime, bus

    tmp_wav = os.path.join(TMP_UPLOADS_ROOT, f"statuina_rec_{int(time.time())}.wav")
    arecord_proc = None

    try:
        # ── 1. Prompt iniziale ──────────────────────────────────────────
        wav_start = _get_or_gen_piper_wav(_PROMPT_START, "prompt_start")
        _play_blocking(wav_start, timeout=30.0)

        # ── 2. Verso del gufo ───────────────────────────────────────────
        owl_wav = _get_or_gen_owl_hoot()
        _play_blocking(owl_wav, timeout=10.0)

        # ── 3. Avvio registrazione ──────────────────────────────────────
        log(f"statuina_record: avvio registrazione per {rfid_code}", "info")
        try:
            arecord_proc = subprocess.Popen(
                ["arecord", "-D", "default", "-f", "S16_LE", "-r", "44100", "-c", "1",
                 "-t", "wav", tmp_wav],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            log("statuina_record: arecord non trovato, impossibile registrare", "error")
            return

        with _lock:
            _state["rec_process"] = arecord_proc
            _state["tmp_wav"] = tmp_wav

        # Aggiorna runtime
        media_runtime["current_mode"] = "statuina_record"
        bus.mark_dirty("media")
        bus.request_emit("public")
        bus.emit_notification("🎤 Registrazione avviata! Parla nel microfono.", "info")

        # ── 4. Attendi stop (pulsante) o timeout 5 minuti ───────────────
        stop_event.wait(timeout=RECORDING_MAX_SECONDS)

        # ── 5. Ferma la registrazione ───────────────────────────────────
        if arecord_proc.poll() is None:
            try:
                arecord_proc.terminate()
                arecord_proc.wait(timeout=5)
            except Exception:
                try:
                    arecord_proc.kill()
                except Exception:
                    pass
        log("statuina_record: registrazione terminata", "info")

        # ── 6. Conversione in MP3 ───────────────────────────────────────
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_rfid = rfid_code.replace(":", "").replace(" ", "")
        mp3_name = f"statuina-{safe_rfid}-{ts}.mp3"
        mp3_path = os.path.join(RECORDINGS_DIR, mp3_name)

        converted = _convert_to_mp3(tmp_wav, mp3_path)

        if converted and os.path.isfile(mp3_path):
            _save_meta(mp3_name, rfid_code, profile_name)
            log(f"statuina_record: registrazione salvata → {mp3_path}", "info")
            bus.emit_notification("✅ Registrazione salvata!", "success")
        else:
            log("statuina_record: conversione MP3 non riuscita, file non salvato", "error")
            bus.emit_notification("⚠️ Errore salvataggio registrazione.", "error")

        # ── 7. Messaggio di completamento ───────────────────────────────
        wav_end = _get_or_gen_piper_wav(_PROMPT_END, "prompt_end")
        _play_blocking(wav_end, timeout=30.0)

    except Exception as e:
        log(f"statuina_record: errore nel thread di registrazione: {e}", "error")

    finally:
        # Pulizia file temporaneo
        try:
            if tmp_wav and os.path.isfile(tmp_wav):
                os.remove(tmp_wav)
        except Exception:
            pass

        # Reimposta stato
        with _lock:
            _state.clear()

        media_runtime["current_mode"] = "idle"
        media_runtime["player_running"] = False
        bus.mark_dirty("media")
        bus.request_emit("public")


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def is_statuina_recording() -> bool:
    """Restituisce True se una registrazione statuina è in corso."""
    with _lock:
        return bool(_state.get("rec_process"))


def start_statuina_recording(rfid_code: str, profile_name: str) -> bool:
    """Avvia il flusso di registrazione in un thread di background.
    Ritorna False se una registrazione è già in corso."""
    with _lock:
        if _state.get("rec_process"):
            log("statuina_record: registrazione già in corso, ignoro nuovo trigger", "warning")
            return False

    stop_event = threading.Event()

    t = threading.Thread(
        target=_recording_thread,
        args=(rfid_code, profile_name, stop_event),
        daemon=True,
        name="statuina-recorder",
    )

    with _lock:
        _state["stop_event"] = stop_event
        _state["thread"] = t

    t.start()
    return True


def stop_statuina_recording() -> None:
    """Ferma la registrazione in corso (equivale alla pressione di play/pausa)."""
    with _lock:
        ev = _state.get("stop_event")
    if ev:
        log("statuina_record: stop richiesto (play/pausa o timeout)", "info")
        ev.set()


def stop_and_wait_statuina_recording(timeout: float = 60.0) -> None:
    """Ferma la registrazione in corso e attende che il thread completi
    (messaggio finale + salvataggio file).  Usato quando una nuova statuina
    viene presentata durante una registrazione attiva.

    Args:
        timeout: secondi massimi di attesa per il completamento del thread
                 (il thread include playback del messaggio finale, ~30 s).
    """
    with _lock:
        ev = _state.get("stop_event")
        t = _state.get("thread")

    if ev:
        log("statuina_record: stop richiesto da nuova statuina, attendo completamento...", "info")
        ev.set()

    if t and t.is_alive():
        t.join(timeout=timeout)
