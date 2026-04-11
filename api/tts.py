"""
api/tts.py - Offline Piper TTS fallback + routing

Endpoints:
  GET  /api/tts/offline/status    - Piper status (installed, voices, cache)
  GET  /api/tts/offline/voices    - list voices in PIPER_VOICES_DIR
  GET  /api/tts/offline/settings  - read current settings
  POST /api/tts/offline/settings  - save settings
  POST /api/tts/offline/test      - generate test audio with Piper
  GET  /api/tts/offline/audio/<f> - serve WAV file from Piper cache
  POST /api/tts/synthesize        - synthesize text (online -> Piper fallback)

Installing Piper on Raspberry Pi:
  1. Download binary from https://github.com/rhasspy/piper/releases
     (e.g. piper_linux_aarch64.tar.gz for RPi 4/5)
  2. Extract and place `piper` in /usr/local/bin/
     or set env GUFOBOX_PIPER_BIN=/path/to/piper
  3. Download a voice model (.onnx + .onnx.json) from
     https://huggingface.co/rhasspy/piper-voices
     and copy it to data/piper_voices/
     Example: it_IT-paola-medium.onnx + it_IT-paola-medium.onnx.json
  4. In the admin panel "Voce offline", select the voice and save.
"""

import hashlib
import os
import re
import subprocess

from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

from config import (
    AI_TTS_CACHE_DIR,
    PIPER_SETTINGS_FILE,
    PIPER_TTS_CACHE_DIR,
    PIPER_VOICES_DIR,
    PIPER_EXECUTABLE,
)
from core.state import load_json, save_json_direct
from core.utils import log

tts_bp = Blueprint("tts", __name__)

# =========================================================
# PIPER SETTINGS
# =========================================================
_DEFAULT_PIPER_SETTINGS = {
    "offline_enabled": False,
    "offline_voice": "",          # voice name without extension, e.g. "it_IT-paola-medium"
    "fallback_policy": "auto",    # "prefer_online" | "auto" | "offline_only"
    "cache_enabled": True,
}

# Allowed characters in voice names (prevent path traversal / injection)
_VOICE_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')
# Maximum length for sanitized error messages returned to clients
_MAX_ERR_LEN = 120
# Allowed Piper voice file extensions
_PIPER_ALLOWED_EXTENSIONS = {".onnx", ".onnx.json"}
# Maximum upload size for a single Piper voice file (50 MB)
_PIPER_MAX_UPLOAD_MB = 50
_PIPER_MAX_UPLOAD_BYTES = _PIPER_MAX_UPLOAD_MB * 1024 * 1024

piper_settings = load_json(PIPER_SETTINGS_FILE, _DEFAULT_PIPER_SETTINGS)


def _save_piper_settings():
    save_json_direct(PIPER_SETTINGS_FILE, piper_settings)


# =========================================================
# PIPER HELPERS
# =========================================================

def _piper_available():
    """Return True if the piper binary responds correctly."""
    try:
        r = subprocess.run(
            [PIPER_EXECUTABLE, "--version"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


def _list_voices():
    """Return sorted list of voice names found in PIPER_VOICES_DIR.
    A voice is any *.onnx file (excluding *.onnx.json).
    """
    try:
        files = os.listdir(PIPER_VOICES_DIR)
    except OSError:
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in files
        if f.endswith(".onnx") and not f.endswith(".onnx.json")
    )


def _piper_cache_key(text, voice):
    return hashlib.md5(f"piper:{voice}:{text}".encode("utf-8")).hexdigest()


def _piper_cache_stats():
    """Return file count and total size of the Piper cache."""
    try:
        entries = [
            os.path.join(PIPER_TTS_CACHE_DIR, f)
            for f in os.listdir(PIPER_TTS_CACHE_DIR)
            if f.endswith(".wav")
        ]
        total_bytes = sum(os.path.getsize(p) for p in entries if os.path.isfile(p))
        return {"files": len(entries), "bytes": total_bytes}
    except OSError:
        return {"files": 0, "bytes": 0}


def _validate_voice_name(voice):
    """Raise ValueError if voice name contains unsafe characters."""
    if not voice or not _VOICE_NAME_RE.match(voice):
        raise ValueError("Nome voce non valido (solo lettere, cifre, trattini e underscore)")


def _resolve_voice_model_path(voice):
    """Return the .onnx path for *voice* by scanning PIPER_VOICES_DIR.

    The returned path is fully derived from the filesystem (not from user
    input), so it cannot introduce path-injection or command-injection.
    Raises ValueError if the voice is not found in the directory.
    """
    _validate_voice_name(voice)
    # Enumerate files from disk — the path used is the fs-derived name
    try:
        entries = os.listdir(PIPER_VOICES_DIR)
    except OSError:
        entries = []
    for entry in entries:
        if entry.endswith(".onnx") and not entry.endswith(".onnx.json"):
            disk_name = os.path.splitext(entry)[0]
            if disk_name == voice:
                # Path constructed entirely from the filesystem-derived entry
                return os.path.join(PIPER_VOICES_DIR, entry)
    raise ValueError("Modello voce non trovato")


def _resolve_cache_wav_path(filename):
    """Return the full path to a WAV file in the Piper cache.

    The path is derived from the filesystem listing (not from the user-provided
    filename), eliminating path-injection. Returns None if not found.
    """
    # Validate format first (32-char lowercase hex + .wav)
    safe_name = os.path.basename(filename)
    if not re.fullmatch(r'[0-9a-fA-F]{32}\.wav', safe_name):
        return None
    try:
        entries = os.listdir(PIPER_TTS_CACHE_DIR)
    except OSError:
        return None
    for entry in entries:
        if entry == safe_name:
            return os.path.join(PIPER_TTS_CACHE_DIR, entry)
    return None


def _safe_error(exc):
    """Return a brief, sanitized error message safe for client responses."""
    return str(exc)[:_MAX_ERR_LEN]


def _validate_piper_upload_filename(filename: str) -> str:
    """Validate and sanitize a Piper voice upload filename.

    Accepts only ``<name>.onnx`` and ``<name>.onnx.json`` where ``<name>``
    matches ``_VOICE_NAME_RE`` (letters, digits, hyphens, underscores).

    Returns the sanitized filename on success.
    Raises ValueError with a human-readable message on failure.
    """
    safe = secure_filename(filename)
    if not safe:
        raise ValueError("Nome file non valido")

    if safe.endswith(".onnx.json"):
        stem = safe[: -len(".onnx.json")]
        ext = ".onnx.json"
    elif safe.endswith(".onnx"):
        stem = safe[: -len(".onnx")]
        ext = ".onnx"
    else:
        raise ValueError(
            "Estensione non consentita. Sono accettati solo file .onnx e .onnx.json"
        )

    if not _VOICE_NAME_RE.match(stem):
        raise ValueError(
            "Nome voce non valido: usa solo lettere, cifre, trattini e underscore"
        )

    return stem + ext


def synthesize_with_piper(text, voice=""):
    """Synthesize text with local Piper. Returns path to WAV file.

    Raises RuntimeError on failure, ValueError on invalid input.
    """
    if not voice:
        voice = piper_settings.get("offline_voice", "")
    if not voice:
        raise RuntimeError("Nessuna voce offline configurata")

    # model_path is derived from the filesystem, not from user input directly
    model_path = _resolve_voice_model_path(voice)

    cache_enabled = piper_settings.get("cache_enabled", True)
    cache_key = _piper_cache_key(text, voice)
    out_path = os.path.join(PIPER_TTS_CACHE_DIR, f"{cache_key}.wav")

    if cache_enabled and os.path.isfile(out_path):
        log(f"Piper TTS cache hit: {cache_key[:8]}", "info")
        return out_path

    # Both model_path (from fs scan) and out_path (from hash) are safe
    cmd = [
        PIPER_EXECUTABLE,
        "--model", model_path,
        "--output_file", out_path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace")[:_MAX_ERR_LEN]
            raise RuntimeError(f"Piper exit {proc.returncode}: {err}")
        log(f"Piper TTS: '{text[:40]}' -> {out_path}", "info")
        return out_path
    except subprocess.TimeoutExpired:
        raise RuntimeError("Piper TTS timeout (>30s)")


def synthesize_text(text, openai_client=None, openai_voice="nova"):
    """Unified TTS routing: try OpenAI first, then Piper as fallback.

    Returns dict with:
        provider  : "openai" | "piper" | "none"
        audio_url : str | None
        error     : str | None  (sanitized, safe to return to client)
    """
    policy = piper_settings.get("fallback_policy", "auto")
    offline_enabled = piper_settings.get("offline_enabled", False)

    # Try OpenAI first (unless offline_only policy)
    if policy != "offline_only" and openai_client is not None:
        try:
            text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
            audio_path = os.path.join(AI_TTS_CACHE_DIR, f"{text_hash}.mp3")
            if not os.path.isfile(audio_path):
                tts_resp = openai_client.audio.speech.create(
                    model="tts-1",
                    voice=openai_voice,
                    input=text,
                )
                tts_resp.stream_to_file(audio_path)
            return {
                "provider": "openai",
                "audio_url": f"/api/ai/tts/{text_hash}.mp3",
                "error": None,
            }
        except Exception as e:
            log(f"OpenAI TTS failed ({e}), trying Piper offline", "warning")
            if not offline_enabled:
                return {"provider": "none", "audio_url": None, "error": "Servizio TTS online non disponibile"}

    # Piper fallback
    if not offline_enabled and policy == "auto":
        return {"provider": "none", "audio_url": None, "error": "Piper offline non abilitato"}

    try:
        wav_path = synthesize_with_piper(text)
        fname = os.path.basename(wav_path)
        return {
            "provider": "piper",
            "audio_url": f"/api/tts/offline/audio/{fname}",
            "error": None,
        }
    except Exception as e:
        log(f"Piper TTS failed: {e}", "error")
        return {"provider": "none", "audio_url": None, "error": "Sintesi vocale offline non riuscita"}


# =========================================================
# ENDPOINTS
# =========================================================

@tts_bp.route("/tts/offline/status", methods=["GET"])
def api_tts_offline_status():
    """Piper status: installed, available voices, cache stats."""
    return jsonify({
        "piper_available": _piper_available(),
        "piper_executable": PIPER_EXECUTABLE,
        "voices_dir": PIPER_VOICES_DIR,
        "voices": _list_voices(),
        "cache": _piper_cache_stats(),
        "settings": piper_settings,
    })


@tts_bp.route("/tts/offline/voices", methods=["GET"])
def api_tts_offline_voices():
    """List available voice names (without .onnx extension)."""
    return jsonify({"voices": _list_voices()})


@tts_bp.route("/tts/offline/settings", methods=["GET"])
def api_tts_offline_settings_get():
    """Read current Piper settings."""
    return jsonify(piper_settings)


@tts_bp.route("/tts/offline/settings", methods=["POST"])
def api_tts_offline_settings_post():
    """Save Piper settings."""
    data = request.get_json(silent=True) or {}
    allowed = {"offline_enabled", "offline_voice", "fallback_policy", "cache_enabled"}
    for k in allowed:
        if k not in data:
            continue
        if k == "offline_voice":
            voice = str(data[k]).strip()
            if voice and not _VOICE_NAME_RE.match(voice):
                return jsonify({"error": "Nome voce non valido"}), 400
            piper_settings[k] = voice
        elif k == "fallback_policy":
            if data[k] not in ("prefer_online", "auto", "offline_only"):
                return jsonify({"error": "Politica di fallback non valida"}), 400
            piper_settings[k] = data[k]
        else:
            piper_settings[k] = data[k]
    _save_piper_settings()
    log("Impostazioni voce offline aggiornate", "info")
    return jsonify({"status": "ok", "settings": piper_settings})


@tts_bp.route("/tts/offline/test", methods=["POST"])
def api_tts_offline_test():
    """Generate a test audio clip with Piper and return its URL."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "Ciao! Sono il Gufetto Magico. Come stai?")
    voice = data.get("voice", piper_settings.get("offline_voice", ""))

    if not _piper_available():
        return jsonify({"error": "Piper non installato o non trovato in PATH"}), 503

    try:
        wav_path = synthesize_with_piper(text, voice=voice)
        fname = os.path.basename(wav_path)
        return jsonify({
            "status": "ok",
            "audio_url": f"/api/tts/offline/audio/{fname}",
            "voice": voice,
        })
    except (ValueError, RuntimeError) as e:
        log(f"Piper test failed: {e}", "error")
        return jsonify({"error": "Sintesi vocale offline non riuscita"}), 500
    except Exception as e:
        log(f"Piper test unexpected error: {e}", "error")
        return jsonify({"error": "Errore interno sintesi vocale"}), 500


@tts_bp.route("/tts/offline/audio/<filename>", methods=["GET"])
def api_tts_offline_serve(filename):
    """Serve a WAV file from the Piper cache."""
    # file_path is derived from the filesystem listing, not from user input
    file_path = _resolve_cache_wav_path(filename)
    if file_path is None:
        return jsonify({"error": "File non trovato"}), 404
    return send_file(file_path, mimetype="audio/wav")


@tts_bp.route("/tts/synthesize", methods=["POST"])
def api_tts_synthesize():
    """Synthesize text: try OpenAI then Piper as fallback."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Testo vuoto"}), 400

    client = None
    try:
        from api.ai import get_openai_client
        client = get_openai_client()
    except Exception:
        pass

    result = synthesize_text(text, openai_client=client)
    if result["provider"] == "none":
        return jsonify({"error": result["error"] or "Sintesi vocale non disponibile"}), 503

    return jsonify({
        "status": "ok",
        "provider": result["provider"],
        "audio_url": result["audio_url"],
    })


@tts_bp.route("/tts/offline/upload", methods=["POST"])
def api_tts_offline_upload():
    """Upload a Piper voice model file (.onnx or .onnx.json) to PIPER_VOICES_DIR.

    Accepts multipart/form-data with a single field named ``file``.
    Only ``.onnx`` and ``.onnx.json`` files are accepted.
    Filenames are sanitized to prevent path traversal.
    Returns the refreshed list of available voices on success.
    """
    if "file" not in request.files:
        return jsonify({"error": "Nessun file nella richiesta"}), 400

    upload = request.files["file"]
    if not upload or not upload.filename:
        return jsonify({"error": "File non valido"}), 400

    try:
        safe_name = _validate_piper_upload_filename(upload.filename)
    except ValueError as exc:
        # Return only the human-readable validation message (no stack trace)
        return jsonify({"error": str(exc)[:_MAX_ERR_LEN]}), 400

    # Guard against oversized uploads
    upload.seek(0, 2)
    file_size = upload.tell()
    upload.seek(0)
    if file_size > _PIPER_MAX_UPLOAD_BYTES:
        return jsonify({"error": f"File troppo grande (max {_PIPER_MAX_UPLOAD_MB} MB)"}), 413

    dest_path = os.path.join(PIPER_VOICES_DIR, safe_name)
    try:
        os.makedirs(PIPER_VOICES_DIR, exist_ok=True)
        upload.save(dest_path)
    except OSError as exc:
        log(f"Piper upload error: {exc}", "error")
        return jsonify({"error": "Errore durante il salvataggio del file"}), 500

    log(f"Piper voice file caricato: {safe_name}", "info")
    return jsonify({
        "status": "ok",
        "filename": safe_name,
        "voices": _list_voices(),
    })
