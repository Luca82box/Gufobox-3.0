"""
api/tts.py - Offline Piper TTS fallback + routing

Endpoints:
  GET  /api/tts/offline/status          - Piper status (installed, voices, cache)
  GET  /api/tts/offline/voices          - list voices in PIPER_VOICES_DIR
  GET  /api/tts/offline/settings        - read current settings
  POST /api/tts/offline/settings        - save settings
  POST /api/tts/offline/test            - generate test audio with Piper
  GET  /api/tts/offline/audio/<f>       - serve WAV file from Piper cache
  POST /api/tts/offline/upload          - upload a Piper voice file (.onnx / .onnx.json)
  POST /api/tts/offline/upload-binary   - upload Piper executable binary
  POST /api/tts/offline/upload-asset    - upload any Piper asset (bin or voices) - folder mode
  GET  /api/tts/offline/suggested-voices - list Italian voices with download URLs
  POST /api/tts/offline/download-binary - auto-download Piper binary from GitHub releases
  POST /api/tts/offline/download-voice  - auto-download voice model from HuggingFace
  POST /api/tts/synthesize              - synthesize text (online -> Piper fallback)

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
import threading

from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

from config import (
    AI_TTS_CACHE_DIR,
    PIPER_MAX_UPLOAD_BYTES,
    PIPER_SETTINGS_FILE,
    PIPER_TTS_CACHE_DIR,
    PIPER_VOICES_DIR,
    PIPER_LOCAL_BIN_DIR,
    PIPER_LOCAL_BIN,
)
import config as _cfg
from core.state import load_json, save_json_direct
from core.utils import log

tts_bp = Blueprint("tts", __name__)

# Lock protecting _cfg.PIPER_EXECUTABLE updates at runtime (e.g. from binary upload)
_piper_exe_lock = threading.Lock()

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
# Maximum upload size for a single Piper voice file — defined in config.py
_PIPER_MAX_UPLOAD_MB = PIPER_MAX_UPLOAD_BYTES // (1024 * 1024)

piper_settings = load_json(PIPER_SETTINGS_FILE, _DEFAULT_PIPER_SETTINGS)


def _save_piper_settings():
    save_json_direct(PIPER_SETTINGS_FILE, piper_settings)


# =========================================================
# PIPER HELPERS
# =========================================================

def _piper_available():
    """Return True if the piper binary responds correctly."""
    with _piper_exe_lock:
        exe = _cfg.PIPER_EXECUTABLE
    try:
        r = subprocess.run(
            [exe, "--version"],
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
    with _piper_exe_lock:
        exe = _cfg.PIPER_EXECUTABLE
    cmd = [
        exe,
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
    with _piper_exe_lock:
        exe = _cfg.PIPER_EXECUTABLE
    local_bin_exists = os.path.isfile(PIPER_LOCAL_BIN)
    available = _piper_available()

    # Build a user-facing diagnostic hint when piper is present but not usable
    diagnosi = None
    if local_bin_exists and not available:
        diagnosi = (
            "Il binario piper è presente ma non risponde. "
            "Possibili cause: architettura sbagliata (serve ARM64 per RPi 4/5), "
            "librerie condivise mancanti (reinstalla tramite 'Scarica binario automaticamente'), "
            "oppure il file non è eseguibile."
        )
    elif not local_bin_exists and exe == "piper":
        diagnosi = (
            "Piper non è installato. Usa il pulsante 'Scarica binario automaticamente' "
            "nel pannello Voce offline oppure carica manualmente il file 'piper' e le "
            "librerie condivise estratte dall'archivio piper_linux_aarch64.tar.gz."
        )

    result = {
        "piper_available": available,
        "piper_executable": exe,
        "piper_local_bin": PIPER_LOCAL_BIN,
        "piper_local_bin_exists": local_bin_exists,
        "voices_dir": PIPER_VOICES_DIR,
        "voices": _list_voices(),
        "cache": _piper_cache_stats(),
        "settings": piper_settings,
    }
    if diagnosi:
        result["diagnosi"] = diagnosi
    return jsonify(result)


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
        # Log the specific validation error but return a static message to avoid
        # any exception details leaking to the client
        log(f"Piper upload validation error: {exc}", "warning")
        return jsonify({"error": "File non valido: estensione o nome voce non consentito"}), 400

    # Guard against oversized uploads
    upload.seek(0, 2)
    file_size = upload.tell()
    upload.seek(0)
    if file_size > PIPER_MAX_UPLOAD_BYTES:
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


@tts_bp.route("/tts/offline/upload-binary", methods=["POST"])
def api_tts_offline_upload_binary():
    """Upload the Piper binary executable to PIPER_LOCAL_BIN_DIR.

    Accepts multipart/form-data with a single field named ``file``.
    The uploaded file is saved as ``data/piper_bin/piper`` and made executable.
    After upload _cfg.PIPER_EXECUTABLE is refreshed to point to the local binary.

    This allows admins to provision Piper on platforms where automatic
    download is not available (e.g. Raspberry Pi with no internet access).
    """
    if "file" not in request.files:
        return jsonify({"error": "Nessun file nella richiesta"}), 400

    upload = request.files["file"]
    if not upload or not upload.filename:
        return jsonify({"error": "File non valido"}), 400

    # Guard against oversized uploads (reuse Piper max size — binary can be up to ~50 MB)
    upload.seek(0, 2)
    file_size = upload.tell()
    upload.seek(0)
    piper_max = _cfg.PIPER_MAX_UPLOAD_BYTES
    if file_size > piper_max:
        return jsonify({"error": f"File troppo grande (max {piper_max // (1024*1024)} MB)"}), 413

    try:
        os.makedirs(PIPER_LOCAL_BIN_DIR, exist_ok=True)
        upload.save(PIPER_LOCAL_BIN)
        # Make the binary executable (chmod +x)
        current_mode = os.stat(PIPER_LOCAL_BIN).st_mode
        os.chmod(PIPER_LOCAL_BIN, current_mode | 0o111)
    except OSError as exc:
        log(f"Piper binary upload error: {exc}", "error")
        return jsonify({"error": "Errore durante il salvataggio del binario"}), 500

    # Refresh the runtime executable path so subsequent calls use the new binary
    with _piper_exe_lock:
        _cfg.PIPER_EXECUTABLE = PIPER_LOCAL_BIN
    log(f"Binario Piper caricato: {PIPER_LOCAL_BIN}", "info")
    return jsonify({
        "status": "ok",
        "piper_executable": PIPER_LOCAL_BIN,
        "piper_available": _piper_available(),
    })


@tts_bp.route("/tts/offline/upload-asset", methods=["POST"])
def api_tts_offline_upload_asset():
    """Upload one or more Piper asset files (any type) to a specified target directory.

    Supports the full Piper asset set: executables, shared libraries, voice models
    (.onnx), config sidecars (.onnx.json), and any other required files.
    This endpoint enables offline / folder-mode provisioning of Piper without internet
    access — the admin extracts the Piper release archive and uploads all files at once.

    Form fields (multipart/form-data):
      files[]:    one or more files to upload
      target_dir: "bin"    → data/piper_bin/    (executables, shared libs)
                  "voices" → data/piper_voices/  (voice models, config JSON)
                  default: "voices"

    Files saved to "bin" are made executable automatically (chmod +x).
    All filenames are sanitised with werkzeug.secure_filename to prevent path traversal.
    """
    target = (request.form.get("target_dir") or "voices").strip().lower()
    if target == "bin":
        dest_dir = PIPER_LOCAL_BIN_DIR
    elif target == "voices":
        dest_dir = PIPER_VOICES_DIR
    else:
        return jsonify({"error": "target_dir non valido. Usa 'bin' o 'voices'."}), 400

    uploaded_files = request.files.getlist("files[]")
    # Also accept a single 'file' field for convenience
    if not uploaded_files or all(not f.filename for f in uploaded_files):
        single = request.files.get("file")
        if single and single.filename:
            uploaded_files = [single]
        else:
            return jsonify({"error": "Nessun file nella richiesta"}), 400

    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as exc:
        log(f"Piper asset upload: impossibile creare la directory {dest_dir}: {exc}", "error")
        return jsonify({"error": "Errore nella creazione della directory di destinazione"}), 500

    max_bytes = _cfg.PIPER_MAX_UPLOAD_BYTES
    real_dest_base = os.path.realpath(dest_dir)
    results = []

    for upload in uploaded_files:
        if not upload or not upload.filename:
            continue

        raw_name = upload.filename
        safe_name = secure_filename(raw_name)
        if not safe_name:
            results.append({"file": raw_name, "ok": False, "error": "Nome file non valido"})
            continue

        # Guard against oversized uploads
        upload.seek(0, 2)
        file_size = upload.tell()
        upload.seek(0)
        if file_size > max_bytes:
            results.append({
                "file": safe_name, "ok": False,
                "error": f"File troppo grande (max {max_bytes // (1024 * 1024)} MB)",
            })
            continue

        dest_path = os.path.join(dest_dir, safe_name)

        # Extra path-traversal guard: ensure resolved dest is inside dest_dir
        real_dest_path = os.path.realpath(dest_path)
        if not real_dest_path.startswith(real_dest_base + os.sep) and real_dest_path != real_dest_base:
            log(f"Piper asset upload: percorso non consentito — {safe_name}", "warning")
            results.append({"file": safe_name, "ok": False, "error": "Percorso non consentito"})
            continue

        try:
            upload.save(dest_path)
            if target == "bin":
                # Make the uploaded file executable (binaries and shared libraries)
                current_mode = os.stat(dest_path).st_mode
                os.chmod(dest_path, current_mode | 0o111)
            results.append({"file": safe_name, "ok": True, "size": file_size})
            log(f"Piper asset caricato: {safe_name} → {dest_dir}", "info")
        except OSError as exc:
            log(f"Piper asset upload error ({safe_name}): {exc}", "error")
            results.append({"file": safe_name, "ok": False, "error": "Errore salvataggio"})

    if not results:
        return jsonify({"error": "Nessun file processato"}), 400

    # Refresh PIPER_EXECUTABLE to point to the local binary if it now exists
    if target == "bin":
        with _piper_exe_lock:
            if os.path.isfile(PIPER_LOCAL_BIN):
                _cfg.PIPER_EXECUTABLE = PIPER_LOCAL_BIN

    ok_count = sum(1 for r in results if r["ok"])
    return jsonify({
        "status": "ok" if ok_count > 0 else "error",
        "results": results,
        "uploaded": ok_count,
        "total": len(results),
        "voices": _list_voices(),
        "piper_available": _piper_available(),
    })


# =========================================================
# AUTO-DOWNLOAD PIPER BINARY
# =========================================================

# Allowed domains for Piper binary downloads (prevent SSRF / arbitrary downloads)
_PIPER_BINARY_ALLOWED_HOSTS = {"github.com", "objects.githubusercontent.com"}

# Allowed domains for voice model downloads
_PIPER_VOICE_ALLOWED_HOSTS = {
    "huggingface.co",
    "cdn-lfs.huggingface.co",
    "cdn-lfs-us-1.huggingface.co",
    "cdn-lfs-eu-1.huggingface.co",
}

# Max size for binary download: 150 MB
_PIPER_BINARY_MAX_BYTES = 150 * 1024 * 1024

# Chunk size for streaming downloads
_DOWNLOAD_CHUNK_SIZE = 64 * 1024


def _checked_download(url: str, dest_path: str, allowed_hosts: set, max_bytes: int,
                       expected_dir: str = None, validate_fn=None) -> dict:
    """
    Scarica un file da *url* in modo sicuro, validando:
    - schema http/https
    - host nella allowlist (previene SSRF)
    - dimensione massima
    - dest_path derivato da config + nome validato (previene path traversal)

    expected_dir: se specificato, verifica che dest_path sia all'interno di
                  questa directory (protezione aggiuntiva contro path traversal).
    validate_fn:  funzione opzionale chiamata con dest_path dopo il download
                  per validazioni aggiuntive sul file salvato.

    Ritorna {"ok": True, "size": N} oppure solleva ValueError/RuntimeError.
    """
    import ssl
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Schema URL non consentito. Usa solo http o https.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL non valido: hostname mancante.")
    if hostname not in allowed_hosts:
        raise ValueError(
            "Provider non consentito. "
            f"Il download è permesso solo da: {', '.join(sorted(allowed_hosts))}."
        )

    # Verifica che dest_path sia all'interno di expected_dir (se fornito)
    if expected_dir is not None:
        real_dest = os.path.realpath(dest_path)
        real_expected = os.path.realpath(expected_dir)
        if real_dest != real_expected and not real_dest.startswith(real_expected + os.sep):
            raise ValueError("Percorso di destinazione non consentito.")

    # Ricostruisci l'URL esclusivamente dai componenti validati (schema + host + path + query)
    # per eliminare ogni possibilità che dati utente non validati raggiungano urlopen.
    safe_url = urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        "",  # strip fragment
    ))

    ctx = ssl.create_default_context() if parsed.scheme == "https" else None
    req = urllib.request.Request(safe_url, headers={"User-Agent": "GufoBox-Piper-Downloader/1.0"})
    open_kwargs: dict = {"timeout": 120}
    if ctx is not None:
        open_kwargs["context"] = ctx

    # Use the fully-validated safe_url (host-allowlisted, reconstructed) -- not raw user input.
    # dest_path comes from os.path.join(trusted_config_dir, regex-validated_filename) in callers.
    safe_dest = os.path.realpath(dest_path)
    size_bytes = 0
    try:
        with urllib.request.urlopen(req, **open_kwargs) as response:  # noqa: S310 -- host validated above
            with open(safe_dest, "wb") as out:
                while True:
                    chunk = response.read(_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        try:
                            os.remove(safe_dest)
                        except OSError:
                            pass
                        raise ValueError(
                            f"File troppo grande (max {max_bytes // (1024 * 1024)} MB)."
                        )
                    out.write(chunk)
    except ValueError:
        raise
    except Exception as exc:
        log(f"Piper download error (network/IO): {exc}", "error")
        raise RuntimeError("Errore durante il download. Controlla i log del server.") from exc

    if validate_fn:
        validate_fn(safe_dest)

    return {"ok": True, "size": size_bytes}


@tts_bp.route("/tts/offline/download-binary", methods=["POST"])
def api_tts_offline_download_binary():
    """Scarica e installa automaticamente il binario Piper da GitHub releases.

    Payload JSON:
      {"url": "https://github.com/rhasspy/piper/releases/download/.../piper_linux_aarch64.tar.gz"}

    Se ``url`` è omesso viene usato l'URL predefinito per Raspberry Pi (aarch64).
    L'intero contenuto dell'archivio tar.gz (binario, librerie condivise, dati espeak-ng)
    viene estratto in ``data/piper_bin/`` in modo che piper possa trovare le sue dipendenze.
    """
    import shutil as _shutil
    import tarfile
    import tempfile

    data = request.get_json(silent=True) or {}
    # Default URL per Raspberry Pi 4/5 a 64 bit (aarch64)
    default_url = (
        "https://github.com/rhasspy/piper/releases/download/"
        "2023.11.14-2/piper_linux_aarch64.tar.gz"
    )
    url = str(data.get("url", default_url)).strip()

    log(f"Avvio download binario Piper da: {url}", "info")

    with tempfile.TemporaryDirectory(prefix="gufobox_piper_dl_") as tmpdir:
        archive_path = os.path.join(tmpdir, "piper.tar.gz")
        try:
            _checked_download(
                url, archive_path, _PIPER_BINARY_ALLOWED_HOSTS, _PIPER_BINARY_MAX_BYTES,
                expected_dir=tmpdir,
            )
        except ValueError as exc:
            log(f"Piper binary download URL error: {exc}", "warning")
            return jsonify({"error": "URL non valido o provider non autorizzato."}), 400
        except RuntimeError:
            return jsonify({"error": "Errore durante il download. Controlla i log del server."}), 502

        # Estrai l'intero archivio tar.gz in modo sicuro.
        # Piper richiede non solo il binario ma anche le librerie condivise
        # (libonnxruntime.so.*, libpiper_phonemize.so.*) e la directory espeak-ng-data.
        # Tutti i file vengono estratti in PIPER_LOCAL_BIN_DIR, rimuovendo il
        # primo livello di directory dell'archivio (es. "piper/piper" -> "piper_bin/piper").
        try:
            local_bin_dir = _cfg.PIPER_LOCAL_BIN_DIR
            local_bin = _cfg.PIPER_LOCAL_BIN
            os.makedirs(local_bin_dir, exist_ok=True)
            real_bin_dir = os.path.realpath(local_bin_dir)

            with tarfile.open(archive_path, "r:gz") as tf:
                # Prima verifica che esista un membro 'piper' (il binario principale)
                piper_member = None
                for m in tf.getmembers():
                    name = m.name.lstrip("./")
                    if (name == "piper" or name.endswith("/piper")) and m.isfile():
                        piper_member = m
                        break
                if piper_member is None:
                    return jsonify({
                        "error": "Binario 'piper' non trovato nell'archivio tar.gz."
                    }), 422

                # Determina il prefisso da rimuovere (es. "piper/" o "piper_linux_aarch64/")
                piper_bin_path = piper_member.name.lstrip("./")
                if "/" in piper_bin_path:
                    strip_prefix = piper_bin_path.rsplit("/", 1)[0] + "/"
                else:
                    strip_prefix = ""

                extracted_count = 0
                for m in tf.getmembers():
                    # Salta symlink e device per sicurezza
                    if not (m.isfile() or m.isdir()):
                        continue
                    rel_name = m.name.lstrip("./")
                    if strip_prefix and rel_name.startswith(strip_prefix):
                        rel_name = rel_name[len(strip_prefix):]
                    if not rel_name:
                        continue

                    # Previeni path traversal
                    dest_path = os.path.realpath(os.path.join(local_bin_dir, rel_name))
                    if not dest_path.startswith(real_bin_dir + os.sep) and dest_path != real_bin_dir:
                        log(f"Piper archive: percorso non sicuro ignorato: {m.name!r}", "warning")
                        continue

                    if m.isdir():
                        os.makedirs(dest_path, exist_ok=True)
                        continue

                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with tf.extractfile(m) as src, open(dest_path, "wb") as dst:
                        while True:
                            chunk = src.read(_DOWNLOAD_CHUNK_SIZE)
                            if not chunk:
                                break
                            dst.write(chunk)
                    extracted_count += 1

            # Rendi eseguibili il binario principale e le librerie condivise
            if os.path.isfile(local_bin):
                current_mode = os.stat(local_bin).st_mode
                os.chmod(local_bin, current_mode | 0o111)
            for entry in os.listdir(local_bin_dir):
                entry_path = os.path.join(local_bin_dir, entry)
                if os.path.isfile(entry_path) and (entry.endswith(".so") or ".so." in entry):
                    current_mode = os.stat(entry_path).st_mode
                    os.chmod(entry_path, current_mode | 0o555)

            log(f"Estratti {extracted_count} file da archivio Piper in {local_bin_dir}", "info")

        except (tarfile.TarError, OSError, Exception) as exc:
            log(f"Piper binary archive extraction error: {exc}", "error")
            return jsonify({"error": "Errore durante l'estrazione dell'archivio tar.gz."}), 422

    # Aggiorna il path eseguibile runtime
    with _piper_exe_lock:
        _cfg.PIPER_EXECUTABLE = _cfg.PIPER_LOCAL_BIN

    available = _piper_available()
    log(f"Binario Piper installato automaticamente: {_cfg.PIPER_LOCAL_BIN} "
        f"(disponibile: {available})", "info")
    return jsonify({
        "status": "ok",
        "piper_executable": _cfg.PIPER_LOCAL_BIN,
        "piper_available": available,
        "url": url,
    })


# =========================================================
# AUTO-DOWNLOAD PIPER VOICE MODEL
# =========================================================

# Max size for a single voice model file: 300 MB (some ONNX models are large)
_PIPER_VOICE_MAX_BYTES = 300 * 1024 * 1024

# Italian voices suggested by default
PIPER_SUGGESTED_VOICES = [
    {
        "name": "it_IT-paola-medium",
        "onnx_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "it/it_IT/paola/medium/it_IT-paola-medium.onnx"
        ),
        "config_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "it/it_IT/paola/medium/it_IT-paola-medium.onnx.json"
        ),
        "description": "Italiano — Paola (qualità media, consigliata)",
    },
    {
        "name": "it_IT-riccardo-x_low",
        "onnx_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "it/it_IT/riccardo/x_low/it_IT-riccardo-x_low.onnx"
        ),
        "config_url": (
            "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "it/it_IT/riccardo/x_low/it_IT-riccardo-x_low.onnx.json"
        ),
        "description": "Italiano — Riccardo (qualità bassa, più veloce)",
    },
]


@tts_bp.route("/tts/offline/suggested-voices", methods=["GET"])
def api_tts_offline_suggested_voices():
    """Restituisce l'elenco delle voci Piper italiane suggerite con URL di download."""
    return jsonify({"voices": PIPER_SUGGESTED_VOICES})


@tts_bp.route("/tts/offline/download-voice", methods=["POST"])
def api_tts_offline_download_voice():
    """Scarica automaticamente un modello voce Piper da HuggingFace.

    Payload JSON:
      {
        "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json"
      }

    Oppure usa il nome di una voce suggerita:
      {"name": "it_IT-paola-medium"}

    Entrambi i file (.onnx e .onnx.json) vengono salvati in ``data/piper_voices/``.
    """
    data = request.get_json(silent=True) or {}

    # Se viene fornito solo il nome, cerca tra le voci suggerite
    voice_name = str(data.get("name", "")).strip()
    if voice_name:
        match = next((v for v in PIPER_SUGGESTED_VOICES if v["name"] == voice_name), None)
        if not match:
            return jsonify({"error": f"Voce suggerita '{voice_name}' non trovata."}), 404
        onnx_url = match["onnx_url"]
        config_url = match["config_url"]
    else:
        onnx_url = str(data.get("onnx_url", "")).strip()
        config_url = str(data.get("config_url", "")).strip()

    if not onnx_url or not config_url:
        return jsonify({
            "error": "Specificare 'name' (voce suggerita) oppure 'onnx_url' e 'config_url'."
        }), 400

    # Ricava il nome del file dall'URL per validarlo
    import urllib.parse
    onnx_filename = os.path.basename(urllib.parse.urlparse(onnx_url).path)
    config_filename = os.path.basename(urllib.parse.urlparse(config_url).path)

    try:
        safe_onnx = _validate_piper_upload_filename(onnx_filename)
        safe_config = _validate_piper_upload_filename(config_filename)
    except ValueError as exc:
        log(f"Piper voice filename validation error: {exc}", "warning")
        return jsonify({"error": "Nome file voce non valido o non consentito."}), 400

    voices_dir = _cfg.PIPER_VOICES_DIR
    os.makedirs(voices_dir, exist_ok=True)
    results = []

    for url_to_dl, safe_name in [(onnx_url, safe_onnx), (config_url, safe_config)]:
        dest_path = os.path.join(voices_dir, safe_name)
        try:
            info = _checked_download(
                url_to_dl, dest_path, _PIPER_VOICE_ALLOWED_HOSTS, _PIPER_VOICE_MAX_BYTES,
                expected_dir=voices_dir,
            )
            results.append({"file": safe_name, "ok": True, "size": info["size"]})
            log(f"Voce Piper scaricata: {safe_name} ({info['size']} bytes)", "info")
        except ValueError as exc:
            log(f"Piper voice download URL error: {exc}", "warning")
            return jsonify({"error": "URL non valido o provider non autorizzato."}), 400
        except RuntimeError:
            return jsonify({"error": "Errore durante il download. Controlla i log del server."}), 502

    return jsonify({
        "status": "ok",
        "files": results,
        "voices": _list_voices(),
    })
