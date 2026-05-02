"""
tests/test_statuina_record_voice.py — PR: flusso registrazione vocale guidata via statuina

Covers:
A) VALID_MODES include statuina_record
B) validate_rfid_profile(): statuina_record non richiede campi aggiuntivi
C) handle_rfid_trigger(): mode=statuina_record avvia start_statuina_recording
D) _exec_statuina_record(): restituisce False se già in corso
E) _trigger_statuina_record(): risposta HTTP corretta
F) core/voice_recorder.py: start_statuina_recording / stop / is_recording
G) play/pause button ferma la registrazione se statuina_record attiva
H) _recording_thread: timeout 5 minuti equivale a play/pausa
I) _recording_thread: converte il file in MP3 192 kbps con ffmpeg
J) _recording_thread: salva il file in RECORDINGS_DIR con meta.json
K) _recording_thread: riproduce prompt iniziale e finale offline
L) Nuova statuina durante registrazione → stop_and_wait poi avvia la nuova
M) stop_and_wait: ferma il thread e attende il completamento
"""

import json
import os
import sys
import threading
import time
from copy import deepcopy
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def rfid_app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    import api.rfid as rfid_module

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-statuina-record-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(rfid_module.rfid_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def rfid_client(rfid_app):
    with rfid_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_rfid_profiles():
    from core.state import rfid_profiles, rfid_map
    original_profiles = deepcopy(dict(rfid_profiles))
    original_map = deepcopy(dict(rfid_map))
    yield
    rfid_profiles.clear()
    rfid_profiles.update(original_profiles)
    rfid_map.clear()
    rfid_map.update(original_map)


@pytest.fixture(autouse=True)
def reset_recorder_state():
    """Pulisce lo stato del voice_recorder dopo ogni test."""
    import core.voice_recorder as vr
    yield
    with vr._lock:
        vr._state.clear()


# ---------------------------------------------------------------------------
# A) VALID_MODES include statuina_record
# ---------------------------------------------------------------------------

def test_valid_modes_includes_statuina_record():
    from api.rfid import VALID_MODES
    assert "statuina_record" in VALID_MODES


# ---------------------------------------------------------------------------
# B) validate_rfid_profile(): statuina_record non richiede campi aggiuntivi
# ---------------------------------------------------------------------------

def test_validate_rfid_profile_statuina_record_no_extra_fields():
    from api.rfid import validate_rfid_profile

    profile = {
        "rfid_code": "SREC01",
        "name": "Registra Voce",
        "mode": "statuina_record",
        "enabled": True,
    }
    profile_dict, error = validate_rfid_profile(profile)
    assert error is None, f"Errori inattesi: {error}"
    assert profile_dict["mode"] == "statuina_record"


# ---------------------------------------------------------------------------
# C) handle_rfid_trigger(): mode=statuina_record chiama start_statuina_recording
# ---------------------------------------------------------------------------

def test_handle_rfid_trigger_statuina_record_calls_start(tmp_path):
    from core.state import rfid_profiles
    from api.rfid import handle_rfid_trigger

    rfid_profiles["SREC01"] = {
        "rfid_code": "SREC01",
        "name": "Registro Voce Guidata",
        "mode": "statuina_record",
        "enabled": True,
    }

    with patch("core.voice_recorder.start_statuina_recording", return_value=True) as mock_start:
        result = handle_rfid_trigger("SREC01")

    assert result is True
    mock_start.assert_called_once_with("SREC01", "Registro Voce Guidata")


# ---------------------------------------------------------------------------
# D) _exec_statuina_record(): restituisce False se registrazione già in corso
# ---------------------------------------------------------------------------

def test_exec_statuina_record_returns_false_when_busy():
    from api.rfid import _exec_statuina_record

    profile = {"name": "Test", "mode": "statuina_record", "enabled": True}

    with patch("core.voice_recorder.start_statuina_recording", return_value=False) as mock_start, \
         patch("core.state.bus.request_emit"), \
         patch("core.state.bus.mark_dirty"), \
         patch("core.state.bus.emit_notification"):
        result = _exec_statuina_record("SREC02", profile)

    assert result is False
    mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# E) _trigger_statuina_record(): risposta HTTP corretta
# ---------------------------------------------------------------------------

def test_trigger_statuina_record_http_ok(rfid_client):
    from core.state import rfid_profiles

    rfid_profiles["SREC03"] = {
        "rfid_code": "SREC03",
        "name": "Registra",
        "mode": "statuina_record",
        "enabled": True,
    }

    with patch("core.voice_recorder.start_statuina_recording", return_value=True):
        resp = rfid_client.post("/api/rfid/trigger", json={"rfid_code": "SREC03"})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["mode"] == "statuina_record"


def test_trigger_statuina_record_http_conflict_when_busy(rfid_client):
    from core.state import rfid_profiles

    rfid_profiles["SREC04"] = {
        "rfid_code": "SREC04",
        "name": "Registra",
        "mode": "statuina_record",
        "enabled": True,
    }

    with patch("core.voice_recorder.start_statuina_recording", return_value=False):
        resp = rfid_client.post("/api/rfid/trigger", json={"rfid_code": "SREC04"})

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# F) core/voice_recorder.py: is / start / stop
# ---------------------------------------------------------------------------

def test_is_statuina_recording_false_initially():
    from core.voice_recorder import is_statuina_recording
    assert is_statuina_recording() is False


def test_stop_statuina_recording_sets_event():
    import core.voice_recorder as vr

    stop_ev = threading.Event()
    with vr._lock:
        vr._state["stop_event"] = stop_ev
        # Fake a process to make is_recording True
        vr._state["rec_process"] = MagicMock()

    assert vr.is_statuina_recording() is True
    vr.stop_statuina_recording()
    assert stop_ev.is_set()


def test_start_statuina_recording_returns_false_when_busy():
    import core.voice_recorder as vr

    with vr._lock:
        vr._state["rec_process"] = MagicMock()

    result = vr.start_statuina_recording("RFID01", "test")
    assert result is False


def test_start_statuina_recording_spawns_thread():
    import core.voice_recorder as vr

    with patch.object(threading.Thread, "start") as mock_start:
        with patch("core.voice_recorder._recording_thread"):
            result = vr.start_statuina_recording("RFID01", "test")

    assert result is True
    mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# G) play/pause button ferma la registrazione se statuina_record attiva
# ---------------------------------------------------------------------------

def test_play_pause_stops_statuina_recording():
    """Il pulsante fisico play/pausa chiama stop_statuina_recording se recording attiva."""
    import core.voice_recorder as vr

    stop_ev = threading.Event()
    with vr._lock:
        vr._state["stop_event"] = stop_ev
        vr._state["rec_process"] = MagicMock()

    # Simula action_play_pause con _DIRECT_AVAILABLE=True
    with patch("hw.buttons._DIRECT_AVAILABLE", True), \
         patch("hw.buttons._send_mpv_command") as mock_mpv, \
         patch("hw.buttons._perform_standby"), \
         patch("hw.buttons._wake_from_standby"), \
         patch("hw.buttons._is_in_standby"):
        from hw.buttons import action_play_pause
        action_play_pause()

    assert stop_ev.is_set(), "stop_statuina_recording non chiamato dal pulsante play/pausa"
    mock_mpv.assert_not_called()   # MPV non deve ricevere il ciclo pause


# ---------------------------------------------------------------------------
# H) Timeout 5 minuti equivale a play/pausa (stop_event.wait timeout)
# ---------------------------------------------------------------------------

def test_recording_timeout_triggers_same_as_button(tmp_path):
    """stop_event.wait(timeout=300) scaduto → stessa logica di pressione button."""
    import core.voice_recorder as vr

    # Patcha tutte le chiamate esterne per isolare la logica
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None   # processo ancora in esecuzione
    mock_proc.terminate.return_value = None
    mock_proc.wait.return_value = 0

    stop_event = threading.Event()
    # Non impostiamo l'evento → scade dopo timeout (ma simuliamo con timeout=0)

    ffmpeg_mp3 = tmp_path / "out.mp3"
    ffmpeg_mp3.write_bytes(b"fake_mp3")

    calls = []

    def fake_play_blocking(path, timeout=60.0):
        if path:
            calls.append(("play", path))

    def fake_convert(wav, mp3):
        # Simula conversione riuscita
        os.makedirs(os.path.dirname(mp3), exist_ok=True)
        with open(mp3, "wb") as f:
            f.write(b"fake_mp3_data")
        return True

    recordings_dir = str(tmp_path / "registrazioni")
    os.makedirs(recordings_dir, exist_ok=True)

    with patch("core.voice_recorder._play_blocking", side_effect=fake_play_blocking), \
         patch("core.voice_recorder._get_or_gen_piper_wav", side_effect=lambda t, k: str(tmp_path / f"{k}.wav")), \
         patch("core.voice_recorder._get_or_gen_owl_hoot", return_value=str(tmp_path / "owl.wav")), \
         patch("core.voice_recorder._convert_to_mp3", side_effect=fake_convert), \
         patch("core.voice_recorder.RECORDINGS_DIR", recordings_dir), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("core.voice_recorder._save_meta"):

        # Avvia il thread con un timeout molto corto
        _orig_max = vr.RECORDING_MAX_SECONDS
        vr.RECORDING_MAX_SECONDS = 0   # scade subito
        try:
            t = threading.Thread(target=vr._recording_thread,
                                 args=("RFID01", "test", stop_event), daemon=True)
            t.start()
            t.join(timeout=10)
        finally:
            vr.RECORDING_MAX_SECONDS = _orig_max

    # Il processo deve essere stato terminato
    mock_proc.terminate.assert_called()


# ---------------------------------------------------------------------------
# I) _recording_thread: converte in MP3 con parametri corretti
# ---------------------------------------------------------------------------

def test_recording_thread_calls_ffmpeg_mp3_params(tmp_path):
    """ffmpeg chiamato con -codec:a libmp3lame -b:a 192k -ar 44100 -ac 1."""
    import core.voice_recorder as vr

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.terminate.return_value = None
    mock_proc.wait.return_value = 0

    stop_event = threading.Event()
    stop_event.set()   # Ferma subito

    recordings_dir = str(tmp_path / "registrazioni")
    os.makedirs(recordings_dir, exist_ok=True)

    ffmpeg_calls = []

    def fake_subprocess_run(cmd, **kwargs):
        if cmd[0] == "ffmpeg":
            ffmpeg_calls.append(cmd)
        m = MagicMock()
        m.returncode = 0
        # Crea il file di output per far sì che os.path.isfile() torni True
        out = cmd[-1]
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(b"mp3")
        return m

    with patch("core.voice_recorder._play_blocking"), \
         patch("core.voice_recorder._get_or_gen_piper_wav", return_value=None), \
         patch("core.voice_recorder._get_or_gen_owl_hoot", return_value=None), \
         patch("core.voice_recorder.RECORDINGS_DIR", recordings_dir), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("subprocess.run", side_effect=fake_subprocess_run), \
         patch("core.voice_recorder._save_meta"):

        _orig_max = vr.RECORDING_MAX_SECONDS
        vr.RECORDING_MAX_SECONDS = 0
        try:
            t = threading.Thread(target=vr._recording_thread,
                                 args=("RFID01", "test", stop_event), daemon=True)
            t.start()
            t.join(timeout=10)
        finally:
            vr.RECORDING_MAX_SECONDS = _orig_max

    assert ffmpeg_calls, "ffmpeg non chiamato"
    cmd = ffmpeg_calls[0]
    assert "-codec:a" in cmd
    assert "libmp3lame" in cmd
    assert "-b:a" in cmd
    assert "192k" in cmd
    assert "-ar" in cmd
    assert "44100" in cmd
    assert "-ac" in cmd
    assert "1" in cmd


# ---------------------------------------------------------------------------
# J) _recording_thread: salva il file in RECORDINGS_DIR con .meta.json
# ---------------------------------------------------------------------------

def test_recording_thread_saves_meta(tmp_path):
    import core.voice_recorder as vr

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.terminate.return_value = None
    mock_proc.wait.return_value = 0

    stop_event = threading.Event()
    stop_event.set()

    recordings_dir = str(tmp_path / "registrazioni")
    os.makedirs(recordings_dir, exist_ok=True)

    saved_metas = []

    def fake_save_meta(mp3_name, rfid_code, profile_name):
        saved_metas.append((mp3_name, rfid_code, profile_name))

    def fake_convert(tmp_wav, mp3_path):
        # Crea il file mp3 finto per far sì che os.path.isfile() torni True
        os.makedirs(os.path.dirname(mp3_path), exist_ok=True)
        with open(mp3_path, "wb") as f:
            f.write(b"fake_mp3")
        return True

    _orig_max = vr.RECORDING_MAX_SECONDS
    vr.RECORDING_MAX_SECONDS = 0
    try:
        with patch("core.voice_recorder._play_blocking"), \
             patch("core.voice_recorder._get_or_gen_piper_wav", return_value=None), \
             patch("core.voice_recorder._get_or_gen_owl_hoot", return_value=None), \
             patch("core.voice_recorder.RECORDINGS_DIR", recordings_dir), \
             patch("subprocess.Popen", return_value=mock_proc), \
             patch("core.voice_recorder._convert_to_mp3", side_effect=fake_convert), \
             patch("core.voice_recorder._save_meta", side_effect=fake_save_meta):

            t = threading.Thread(target=vr._recording_thread,
                                 args=("RFID:01", "Mia Voce", stop_event), daemon=True)
            t.start()
            t.join(timeout=10)
    finally:
        vr.RECORDING_MAX_SECONDS = _orig_max

    # _save_meta deve essere stata chiamata
    assert saved_metas, "_save_meta non chiamata"
    _mp3_name, rfid_code, profile_name = saved_metas[0]
    assert rfid_code == "RFID:01"
    assert profile_name == "Mia Voce"
    assert _mp3_name.endswith(".mp3")
    assert _mp3_name.startswith("statuina-")


# ---------------------------------------------------------------------------
# K) _recording_thread: riproduce prompt iniziale e finale
# ---------------------------------------------------------------------------

def test_recording_thread_plays_both_prompts(tmp_path):
    import core.voice_recorder as vr

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.terminate.return_value = None
    mock_proc.wait.return_value = 0

    stop_event = threading.Event()
    stop_event.set()

    recordings_dir = str(tmp_path / "registrazioni")
    os.makedirs(recordings_dir, exist_ok=True)

    played_paths = []

    def fake_play_blocking(path, timeout=60.0):
        if path:
            played_paths.append(path)

    prompt_paths = {
        "prompt_start": str(tmp_path / "prompt_start.wav"),
        "prompt_end": str(tmp_path / "prompt_end.wav"),
    }
    owl_path = str(tmp_path / "owl_hoot.wav")
    # Crea i file finti
    for p in list(prompt_paths.values()) + [owl_path]:
        open(p, "wb").write(b"wav")

    with patch("core.voice_recorder._play_blocking", side_effect=fake_play_blocking), \
         patch("core.voice_recorder._get_or_gen_piper_wav",
               side_effect=lambda t, k: prompt_paths.get(k)), \
         patch("core.voice_recorder._get_or_gen_owl_hoot", return_value=owl_path), \
         patch("core.voice_recorder.RECORDINGS_DIR", recordings_dir), \
         patch("subprocess.Popen", return_value=mock_proc), \
         patch("core.voice_recorder._convert_to_mp3", return_value=True), \
         patch("core.voice_recorder._save_meta"):

        _orig_max = vr.RECORDING_MAX_SECONDS
        vr.RECORDING_MAX_SECONDS = 0
        try:
            t = threading.Thread(target=vr._recording_thread,
                                 args=("RFID01", "test", stop_event), daemon=True)
            t.start()
            t.join(timeout=10)
        finally:
            vr.RECORDING_MAX_SECONDS = _orig_max

    # Deve aver riprodotto: prompt_start, owl_hoot, prompt_end
    assert prompt_paths["prompt_start"] in played_paths, "Prompt iniziale non riprodotto"
    assert owl_path in played_paths, "Verso del gufo non riprodotto"
    assert prompt_paths["prompt_end"] in played_paths, "Prompt finale non riprodotto"
    # L'ordine deve essere corretto
    idx_start = played_paths.index(prompt_paths["prompt_start"])
    idx_owl = played_paths.index(owl_path)
    idx_end = played_paths.index(prompt_paths["prompt_end"])
    assert idx_start < idx_owl < idx_end, "Ordine riproduzione non corretto"


# ---------------------------------------------------------------------------
# L) Nuova statuina durante registrazione → stop_and_wait poi avvia la nuova
# ---------------------------------------------------------------------------

def test_new_statuina_during_recording_stops_and_waits_then_triggers(tmp_path):
    """handle_rfid_trigger: se statuina_record attiva, chiama stop_and_wait prima
    di avviare il nuovo profilo."""
    from core.state import rfid_profiles
    from api.rfid import handle_rfid_trigger

    # Profilo della nuova statuina (non statuina_record)
    rfid_profiles["NEW01"] = {
        "rfid_code": "NEW01",
        "name": "Nuova Statuina",
        "mode": "media_folder",
        "folder": str(tmp_path),
        "enabled": True,
    }

    call_order = []

    def fake_stop_and_wait(timeout=60.0):
        call_order.append("stop_and_wait")

    def fake_exec_media_folder(rfid_code, profile):
        call_order.append("exec_media_folder")
        return True

    with patch("core.voice_recorder.is_statuina_recording", return_value=True), \
         patch("core.voice_recorder.stop_and_wait_statuina_recording",
               side_effect=fake_stop_and_wait), \
         patch("api.rfid._exec_media_folder", side_effect=fake_exec_media_folder):
        result = handle_rfid_trigger("NEW01")

    assert result is True
    assert call_order == ["stop_and_wait", "exec_media_folder"], (
        f"Ordine atteso: stop_and_wait → exec_media_folder. Ottenuto: {call_order}"
    )


def test_new_statuina_via_http_stops_and_waits_then_triggers(rfid_client):
    """POST /rfid/trigger: se statuina_record attiva, chiama stop_and_wait prima
    di rispondere al nuovo trigger."""
    from core.state import rfid_profiles

    rfid_profiles["NEW02"] = {
        "rfid_code": "NEW02",
        "name": "Nuova Statuina HTTP",
        "mode": "statuina_record",
        "enabled": True,
    }

    call_order = []

    def fake_stop_and_wait(timeout=60.0):
        call_order.append("stop_and_wait")

    def fake_start(rfid_code, profile_name):
        call_order.append("start_recording")
        return True

    with patch("core.voice_recorder.is_statuina_recording", return_value=True), \
         patch("core.voice_recorder.stop_and_wait_statuina_recording",
               side_effect=fake_stop_and_wait), \
         patch("core.voice_recorder.start_statuina_recording", side_effect=fake_start):
        resp = rfid_client.post("/api/rfid/trigger", json={"rfid_code": "NEW02"})

    assert resp.status_code == 200
    assert "stop_and_wait" in call_order
    assert call_order.index("stop_and_wait") < call_order.index("start_recording"), (
        "stop_and_wait deve avvenire prima di start_recording"
    )


# ---------------------------------------------------------------------------
# M) stop_and_wait: ferma il thread e attende il completamento
# ---------------------------------------------------------------------------

def test_stop_and_wait_sets_event_and_joins_thread():
    import core.voice_recorder as vr

    stop_ev = threading.Event()
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = True

    with vr._lock:
        vr._state["stop_event"] = stop_ev
        vr._state["rec_process"] = MagicMock()
        vr._state["thread"] = mock_thread

    vr.stop_and_wait_statuina_recording(timeout=5.0)

    assert stop_ev.is_set(), "stop_event non impostato"
    mock_thread.join.assert_called_once_with(timeout=5.0)


def test_stop_and_wait_no_recording_is_noop():
    """stop_and_wait non solleva eccezioni se nessuna registrazione è in corso."""
    import core.voice_recorder as vr
    # _state è vuoto (reset dall'autouse fixture)
    vr.stop_and_wait_statuina_recording(timeout=1.0)   # deve passare silenziosamente
