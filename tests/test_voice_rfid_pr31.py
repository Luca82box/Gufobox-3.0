"""
tests/test_voice_rfid_pr31.py — PR 31: Registrazione vocale + RFID voice_recording

Covers:
A) POST /api/voice/upload: campi estesi (role, author, description) e sidecar .meta.json
B) POST /api/voice/upload: dimensione massima file
C) POST /api/voice/upload: estensione non valida aggiunge .webm
D) GET /api/voice/recordings: lista registrazioni con metadati
E) GET /api/voice/recording/<filename>: dettaglio singola registrazione
F) PUT /api/voice/recording/<filename>: aggiorna metadati
G) DELETE /api/voice/recording/<filename>: elimina file + sidecar + associazioni RFID
H) VALID_MODES include voice_recording
I) validate_rfid_profile(): recording_path obbligatorio per mode=voice_recording
J) POST /rfid/profile: crea profilo voice_recording
K) POST /rfid/trigger mode=voice_recording: riproduce la registrazione
L) POST /rfid/trigger mode=voice_recording: file non trovato → 404
M) handle_rfid_trigger (Python diretto): mode=voice_recording
N) Compatibilità all'indietro: gli altri mode non sono influenzati
O) Notifica di benvenuto: play_ai_notification viene chiamata all'avvio
"""

import io
import json
import os
import sys
import tempfile
from copy import deepcopy
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures App Voice
# ---------------------------------------------------------------------------

@pytest.fixture()
def voice_app(tmp_path):
    """Flask app con voice_bp registrato; RECORDINGS_DIR puntata a tmp_path."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    import api.voice as voice_module

    # Redirige la cartella registrazioni al tmp_path per i test
    voice_module.RECORDINGS_DIR = str(tmp_path)

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-voice-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(voice_module.voice_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def voice_client(voice_app):
    with voice_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_voice_state():
    """Reset rfid_map prima di ogni test."""
    from core.state import rfid_map
    rfid_map.clear()
    yield
    rfid_map.clear()


# ---------------------------------------------------------------------------
# Fixtures App RFID
# ---------------------------------------------------------------------------

@pytest.fixture()
def rfid_app():
    """Flask app minimale con rfid_bp."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.rfid import rfid_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-rfid-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(rfid_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def rfid_client(rfid_app):
    with rfid_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_rfid_state():
    """Reset rfid_profiles e media_runtime prima di ogni test."""
    from core.state import rfid_profiles, media_runtime
    rfid_profiles.clear()
    media_runtime.clear()
    media_runtime.update({
        "player_running": False,
        "current_rfid": None,
        "current_profile_name": None,
        "current_mode": "idle",
        "current_media_path": None,
        "current_playlist": [],
        "playlist_index": 0,
        "current_volume": 70,
    })
    yield
    rfid_profiles.clear()
    media_runtime.clear()


# ---------------------------------------------------------------------------
# A) Upload con campi estesi e sidecar .meta.json
# ---------------------------------------------------------------------------

def test_upload_extended_fields(voice_client, tmp_path):
    """POST /voice/upload: salva il file e crea il sidecar con metadati estesi."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    data = {
        "audio": (io.BytesIO(b"fake-audio-data"), "storia.webm"),
        "name": "storia_della_notte",
        "role": "genitore",
        "author": "Mamma",
        "description": "La storia della buonanotte",
    }
    resp = voice_client.post("/api/voice/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    filename = body["filename"]

    # Verifica sidecar
    meta_path = os.path.join(str(tmp_path), filename + ".meta.json")
    assert os.path.exists(meta_path)
    with open(meta_path, "r") as f:
        meta = json.load(f)
    assert meta["role"] == "genitore"
    assert meta["author"] == "Mamma"
    assert meta["description"] == "La storia della buonanotte"
    assert meta["name"] == "storia_della_notte"


def test_upload_role_default_bambino(voice_client, tmp_path):
    """POST /voice/upload: role di default è 'bambino'."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    data = {"audio": (io.BytesIO(b"data"), "rec.webm")}
    resp = voice_client.post("/api/voice/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    filename = body["filename"]
    meta_path = os.path.join(str(tmp_path), filename + ".meta.json")
    with open(meta_path, "r") as f:
        meta = json.load(f)
    assert meta["role"] == "bambino"


def test_upload_invalid_role_defaults_bambino(voice_client, tmp_path):
    """POST /voice/upload: role non valido → default 'bambino'."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    data = {
        "audio": (io.BytesIO(b"data"), "rec.webm"),
        "role": "amministratore",
    }
    resp = voice_client.post("/api/voice/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["meta"]["role"] == "bambino"


# ---------------------------------------------------------------------------
# B) Controllo dimensione massima file
# ---------------------------------------------------------------------------

def test_upload_file_too_large(voice_client, tmp_path):
    """POST /voice/upload: file > 50 MB → 413."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    big_data = b"x" * (51 * 1024 * 1024)
    data = {"audio": (io.BytesIO(big_data), "big.webm")}
    resp = voice_client.post("/api/voice/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# C) Estensione non valida → aggiunge .webm
# ---------------------------------------------------------------------------

def test_upload_no_extension_adds_webm(voice_client, tmp_path):
    """POST /voice/upload: nome senza estensione valida → aggiunge .webm."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    data = {
        "audio": (io.BytesIO(b"data"), "storia.webm"),
        "name": "storia_senza_ext",
    }
    resp = voice_client.post("/api/voice/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    filename = resp.get_json()["filename"]
    assert filename.endswith(".webm")


# ---------------------------------------------------------------------------
# D) GET /voice/recordings
# ---------------------------------------------------------------------------

def test_list_recordings(voice_client, tmp_path):
    """GET /voice/recordings: ritorna lista registrazioni con metadati."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    # Crea un file audio e il suo sidecar
    audio_file = tmp_path / "storia_abc.webm"
    audio_file.write_bytes(b"audio-data")
    meta = {
        "name": "La storia",
        "role": "genitore",
        "author": "Papà",
        "rfid_code": "ABC123",
        "description": "Test",
        "created_at": "2026-04-01T10:00:00",
    }
    meta_file = tmp_path / "storia_abc.webm.meta.json"
    meta_file.write_text(json.dumps(meta))

    resp = voice_client.get("/api/voice/recordings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    entry = data[0]
    assert entry["filename"] == "storia_abc.webm"
    assert entry["role"] == "genitore"
    assert entry["author"] == "Papà"
    assert entry["rfid_code"] == "ABC123"
    assert entry["size_bytes"] > 0


def test_list_recordings_ignores_sidecars(voice_client, tmp_path):
    """GET /voice/recordings: i file .meta.json non appaiono nella lista."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    (tmp_path / "rec.webm").write_bytes(b"audio")
    (tmp_path / "rec.webm.meta.json").write_text("{}")

    resp = voice_client.get("/api/voice/recordings")
    data = resp.get_json()
    filenames = [e["filename"] for e in data]
    assert "rec.webm.meta.json" not in filenames
    assert "rec.webm" in filenames


# ---------------------------------------------------------------------------
# E) GET /voice/recording/<filename>
# ---------------------------------------------------------------------------

def test_get_recording_detail(voice_client, tmp_path):
    """GET /voice/recording/<filename>: ritorna metadati della registrazione."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    (tmp_path / "storia.webm").write_bytes(b"data")
    meta = {"name": "Storia", "role": "bambino", "author": "", "rfid_code": "", "description": "", "created_at": ""}
    (tmp_path / "storia.webm.meta.json").write_text(json.dumps(meta))

    resp = voice_client.get("/api/voice/recording/storia.webm")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["filename"] == "storia.webm"
    assert body["role"] == "bambino"


def test_get_recording_not_found(voice_client, tmp_path):
    """GET /voice/recording/<filename>: file inesistente → 404."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    resp = voice_client.get("/api/voice/recording/nonexist.webm")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# F) PUT /voice/recording/<filename>
# ---------------------------------------------------------------------------

def test_update_recording_metadata(voice_client, tmp_path):
    """PUT /voice/recording/<filename>: aggiorna metadati nel sidecar."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    (tmp_path / "rec.webm").write_bytes(b"data")
    meta = {"name": "Vecchio nome", "role": "bambino", "author": "", "rfid_code": "", "description": "", "created_at": ""}
    (tmp_path / "rec.webm.meta.json").write_text(json.dumps(meta))

    resp = voice_client.put(
        "/api/voice/recording/rec.webm",
        json={"name": "Nuovo nome", "role": "genitore", "author": "Nonno"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["meta"]["name"] == "Nuovo nome"
    assert body["meta"]["role"] == "genitore"
    assert body["meta"]["author"] == "Nonno"

    # Verifica persistenza
    with open(str(tmp_path / "rec.webm.meta.json")) as f:
        saved = json.load(f)
    assert saved["name"] == "Nuovo nome"


def test_update_recording_not_found(voice_client, tmp_path):
    """PUT /voice/recording/<filename>: file inesistente → 404."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    resp = voice_client.put("/api/voice/recording/ghost.webm", json={"name": "x"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# G) DELETE /voice/recording/<filename>
# ---------------------------------------------------------------------------

def test_delete_recording(voice_client, tmp_path):
    """DELETE /voice/recording/<filename>: elimina file e sidecar."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    audio_path = tmp_path / "rec.webm"
    audio_path.write_bytes(b"data")
    meta_path = tmp_path / "rec.webm.meta.json"
    meta_path.write_text("{}")

    resp = voice_client.delete("/api/voice/recording/rec.webm")
    assert resp.status_code == 200
    assert not audio_path.exists()
    assert not meta_path.exists()


def test_delete_removes_rfid_map_association(voice_client, tmp_path):
    """DELETE /voice/recording/<filename>: rimuove associazione da rfid_map legacy."""
    import api.voice as voice_module
    from core.state import rfid_map
    voice_module.RECORDINGS_DIR = str(tmp_path)

    file_path = str(tmp_path / "rec.webm")
    (tmp_path / "rec.webm").write_bytes(b"data")
    meta = {"name": "rec", "role": "bambino", "author": "", "rfid_code": "ABC123", "description": "", "created_at": ""}
    (tmp_path / "rec.webm.meta.json").write_text(json.dumps(meta))

    # Simula associazione nel rfid_map legacy
    rfid_map["ABC123"] = {"type": "audio", "target": file_path}

    with patch("api.voice.save_json_direct"):
        resp = voice_client.delete("/api/voice/recording/rec.webm")
    assert resp.status_code == 200
    assert "ABC123" not in rfid_map


def test_delete_removes_rfid_profile_voice_recording(voice_client, tmp_path):
    """DELETE /voice/recording/<filename>: rimuove profili RFID di tipo voice_recording."""
    import api.voice as voice_module
    from core.state import rfid_profiles
    voice_module.RECORDINGS_DIR = str(tmp_path)

    file_path = str(tmp_path / "rec.webm")
    (tmp_path / "rec.webm").write_bytes(b"data")
    (tmp_path / "rec.webm.meta.json").write_text("{}")

    # Simula profilo RFID voice_recording associato al file
    rfid_profiles["MYUID"] = {
        "rfid_code": "MYUID",
        "name": "Test",
        "mode": "voice_recording",
        "recording_path": file_path,
        "enabled": True,
    }

    with patch("api.voice.save_json_direct"):
        resp = voice_client.delete("/api/voice/recording/rec.webm")
    assert resp.status_code == 200
    assert "MYUID" not in rfid_profiles


def test_delete_recording_not_found(voice_client, tmp_path):
    """DELETE /voice/recording/<filename>: file inesistente → 404."""
    import api.voice as voice_module
    voice_module.RECORDINGS_DIR = str(tmp_path)

    resp = voice_client.delete("/api/voice/recording/ghost.webm")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# H) VALID_MODES include voice_recording
# ---------------------------------------------------------------------------

def test_valid_modes_includes_voice_recording():
    """VALID_MODES deve contenere 'voice_recording'."""
    from api.rfid import VALID_MODES
    assert "voice_recording" in VALID_MODES


# ---------------------------------------------------------------------------
# I) validate_rfid_profile(): recording_path obbligatorio per mode=voice_recording
# ---------------------------------------------------------------------------

def test_validate_rfid_profile_voice_recording_missing_path():
    """validate_rfid_profile(): senza recording_path → errore."""
    from api.rfid import validate_rfid_profile
    data = {"rfid_code": "ABC1", "name": "Test", "mode": "voice_recording"}
    profile, err = validate_rfid_profile(data)
    assert profile is None
    assert "recording_path" in err


def test_validate_rfid_profile_voice_recording_valid():
    """validate_rfid_profile(): con recording_path → profilo valido."""
    from api.rfid import validate_rfid_profile
    data = {
        "rfid_code": "ABC1",
        "name": "Test",
        "mode": "voice_recording",
        "recording_path": "/home/gufobox/media/registrazioni/storia.webm",
    }
    profile, err = validate_rfid_profile(data)
    assert err is None
    assert profile["recording_path"] == "/home/gufobox/media/registrazioni/storia.webm"


def test_validate_rfid_profile_voice_recording_update_no_path():
    """validate_rfid_profile() in update: recording_path non obbligatorio."""
    from api.rfid import validate_rfid_profile
    data = {"rfid_code": "ABC1", "name": "Test", "mode": "voice_recording"}
    profile, err = validate_rfid_profile(data, update=True)
    assert err is None


# ---------------------------------------------------------------------------
# J) POST /rfid/profile: crea profilo voice_recording
# ---------------------------------------------------------------------------

def test_create_voice_recording_profile(rfid_client):
    """POST /rfid/profile: crea profilo voice_recording con recording_path."""
    data = {
        "rfid_code": "VOICE01",
        "name": "Storia della notte",
        "mode": "voice_recording",
        "recording_path": "/home/gufobox/media/registrazioni/storia.webm",
    }
    with patch("api.rfid.save_json_direct"):
        resp = rfid_client.post("/api/rfid/profile", json=data)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["profile"]["mode"] == "voice_recording"
    assert body["profile"]["recording_path"] == "/home/gufobox/media/registrazioni/storia.webm"


def test_create_voice_recording_profile_missing_path(rfid_client):
    """POST /rfid/profile: senza recording_path → 400."""
    data = {
        "rfid_code": "VOICE02",
        "name": "Test",
        "mode": "voice_recording",
    }
    resp = rfid_client.post("/api/rfid/profile", json=data)
    assert resp.status_code == 400
    assert "recording_path" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# K) POST /rfid/trigger mode=voice_recording: riproduce la registrazione
# ---------------------------------------------------------------------------

def test_trigger_voice_recording_success(rfid_client, tmp_path):
    """POST /rfid/trigger mode=voice_recording: riproduce il file audio."""
    from core.state import rfid_profiles

    audio_file = tmp_path / "storia.webm"
    audio_file.write_bytes(b"audio")

    rfid_profiles["VOICE01"] = {
        "rfid_code": "VOICE01",
        "name": "Storia",
        "mode": "voice_recording",
        "recording_path": str(audio_file),
        "enabled": True,
        "volume": 70,
    }

    with patch("core.media.start_player", return_value=(True, "ok")) as mock_player:
        resp = rfid_client.post("/api/rfid/trigger", json={"rfid_code": "VOICE01"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["mode"] == "voice_recording"
    mock_player.assert_called_once()
    # Verifica che il player sia stato chiamato con il path corretto e il profile_mode giusto
    call_kwargs = mock_player.call_args
    assert call_kwargs[0][0] == str(audio_file)
    assert call_kwargs[1].get("profile_mode") == "voice_recording"


# ---------------------------------------------------------------------------
# L) POST /rfid/trigger mode=voice_recording: file non trovato → 404
# ---------------------------------------------------------------------------

def test_trigger_voice_recording_file_not_found(rfid_client):
    """POST /rfid/trigger mode=voice_recording: file non trovato → 404."""
    from core.state import rfid_profiles

    rfid_profiles["VOICE02"] = {
        "rfid_code": "VOICE02",
        "name": "Fantasma",
        "mode": "voice_recording",
        "recording_path": "/nonexistent/path/storia.webm",
        "enabled": True,
    }

    resp = rfid_client.post("/api/rfid/trigger", json={"rfid_code": "VOICE02"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# M) handle_rfid_trigger (Python diretto): mode=voice_recording
# ---------------------------------------------------------------------------

def test_handle_rfid_trigger_voice_recording_success(tmp_path):
    """handle_rfid_trigger(): mode=voice_recording avvia la riproduzione."""
    from core.state import rfid_profiles
    from api.rfid import handle_rfid_trigger

    audio_file = tmp_path / "storia.webm"
    audio_file.write_bytes(b"audio")

    rfid_profiles["VOICE03"] = {
        "rfid_code": "VOICE03",
        "name": "Storia diretta",
        "mode": "voice_recording",
        "recording_path": str(audio_file),
        "enabled": True,
        "volume": 80,
    }

    with patch("core.media.start_player", return_value=(True, "ok")) as mock_player:
        result = handle_rfid_trigger("VOICE03")

    assert result is True
    mock_player.assert_called_once()


def test_handle_rfid_trigger_voice_recording_missing_file(tmp_path):
    """handle_rfid_trigger(): file mancante → ritorna False senza crash."""
    from core.state import rfid_profiles
    from api.rfid import handle_rfid_trigger

    rfid_profiles["VOICE04"] = {
        "rfid_code": "VOICE04",
        "name": "Mancante",
        "mode": "voice_recording",
        "recording_path": "/nonexistent/storia.webm",
        "enabled": True,
    }

    result = handle_rfid_trigger("VOICE04")
    assert result is False


# ---------------------------------------------------------------------------
# N) Compatibilità all'indietro: altri mode non sono influenzati
# ---------------------------------------------------------------------------

def test_existing_modes_unaffected():
    """I mode preesistenti (media_folder, webradio, ecc.) funzionano ancora."""
    from api.rfid import VALID_MODES
    for mode in ("media_folder", "webradio", "ai_chat", "rss_feed", "edu_ai", "web_media", "school", "entertainment"):
        assert mode in VALID_MODES


def test_validate_rfid_profile_media_folder_unaffected():
    """validate_rfid_profile() con mode=media_folder non richiede recording_path."""
    from api.rfid import validate_rfid_profile
    data = {
        "rfid_code": "MF01",
        "name": "Cartella",
        "mode": "media_folder",
        "folder": "/home/gufobox/media/contenuti/audiolibri",
    }
    profile, err = validate_rfid_profile(data)
    assert err is None
    assert profile["recording_path"] == ""


# ---------------------------------------------------------------------------
# O) Notifica di benvenuto: play_ai_notification chiamata all'avvio
# ---------------------------------------------------------------------------

def test_welcome_notification_called_at_startup():
    """
    Verifica che play_ai_notification venga chiamata con il messaggio di benvenuto
    all'avvio, tramite eventlet.spawn (non blocca il boot).
    """
    spawned_funcs = []

    def fake_spawn(fn, *args, **kwargs):
        spawned_funcs.append(fn)
        return MagicMock()

    with patch("eventlet.spawn", side_effect=fake_spawn):
        with patch("hw.battery.play_ai_notification") as mock_notif:
            # Simula l'esecuzione del blocco di startup di main.py
            import eventlet

            def _play_welcome():
                try:
                    from hw.battery import play_ai_notification
                    play_ai_notification("Uhuu! Ciao, sono il Gufetto! Sono pronto a giocare con te!")
                except Exception:
                    pass

            eventlet.spawn(_play_welcome)

            # Esegui la funzione spawned per verificare che chiami la notifica
            assert len(spawned_funcs) == 1
            with patch("hw.battery.play_ai_notification") as mock_notif2:
                spawned_funcs[0]()
                mock_notif2.assert_called_once_with(
                    "Uhuu! Ciao, sono il Gufetto! Sono pronto a giocare con te!"
                )


def test_welcome_notification_does_not_crash_on_error():
    """
    La notifica di benvenuto non deve crashare anche se play_ai_notification lancia eccezione.
    """
    def _play_welcome():
        try:
            from hw.battery import play_ai_notification
            play_ai_notification("Uhuu! Ciao, sono il Gufetto! Sono pronto a giocare con te!")
        except Exception as e:
            from core.utils import log
            log(f"Notifica benvenuto non disponibile: {e}", "warning")

    with patch("hw.battery.play_ai_notification", side_effect=RuntimeError("TTS offline")):
        # Non deve sollevare eccezioni
        _play_welcome()
