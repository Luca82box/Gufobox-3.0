"""
tests/test_offline_voice_pr33.py — Test per le funzionalità aggiunte in PR-33

Copre:
- POST /api/tts/offline/upload: upload file voce Piper
  - file .onnx valido
  - file .onnx.json valido
  - estensione non consentita
  - filename con path traversal
  - richiesta senza file
  - file vuoto / nome vuoto
- _validate_piper_upload_filename (unit test diretto)
- GET /api/ai/status: campo openai_configured
- POST /api/ai/settings: salvataggio / rimozione / mascheratura chiave API OpenAI
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_auth_state():
    from core.state import state
    state.pop("auth", None)
    yield
    state.pop("auth", None)


@pytest.fixture()
def tmp_voices_dir(tmp_path, monkeypatch):
    """Override PIPER_VOICES_DIR with a temporary directory."""
    import api.tts as tts_module
    import config as cfg
    voices_dir = tmp_path / "piper_voices"
    voices_dir.mkdir()
    monkeypatch.setattr(tts_module, "PIPER_VOICES_DIR", str(voices_dir))
    monkeypatch.setattr(cfg, "PIPER_VOICES_DIR", str(voices_dir))
    return voices_dir


@pytest.fixture()
def app(tmp_voices_dir):
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.auth import auth_bp
    from api.tts import tts_bp
    from api.ai import ai_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-offline-voice-secret"
    flask_app.config["TESTING"] = True
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    CORS(flask_app, supports_credentials=True)
    flask_app.register_blueprint(auth_bp, url_prefix="/api")
    flask_app.register_blueprint(tts_bp, url_prefix="/api")
    flask_app.register_blueprint(ai_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ─── unit tests: _validate_piper_upload_filename ─────────────────────────────

def test_validate_valid_onnx():
    from api.tts import _validate_piper_upload_filename
    assert _validate_piper_upload_filename("it_IT-paola-medium.onnx") == "it_IT-paola-medium.onnx"


def test_validate_valid_onnx_json():
    from api.tts import _validate_piper_upload_filename
    assert _validate_piper_upload_filename("it_IT-paola-medium.onnx.json") == "it_IT-paola-medium.onnx.json"


def test_validate_rejects_txt():
    from api.tts import _validate_piper_upload_filename
    with pytest.raises(ValueError, match="Estensione non consentita"):
        _validate_piper_upload_filename("malicious.txt")


def test_validate_rejects_py():
    from api.tts import _validate_piper_upload_filename
    with pytest.raises(ValueError):
        _validate_piper_upload_filename("evil.py")


def test_validate_path_traversal_is_sanitized():
    from api.tts import _validate_piper_upload_filename
    # werkzeug.secure_filename strips all separators so "../../evil.onnx" -> "evil.onnx"
    # which IS safe — the security guarantee is that no path can escape PIPER_VOICES_DIR.
    result = _validate_piper_upload_filename("../../evil.onnx")
    assert ".." not in result
    assert "/" not in result
    assert "\\" not in result
    assert result.endswith(".onnx")


def test_validate_rejects_empty_filename():
    from api.tts import _validate_piper_upload_filename
    with pytest.raises(ValueError):
        _validate_piper_upload_filename("")


def test_validate_rejects_all_special_chars_stem():
    from api.tts import _validate_piper_upload_filename
    # stem becomes empty after secure_filename strips all special chars
    with pytest.raises(ValueError):
        _validate_piper_upload_filename("!@#$.onnx")


# ─── upload endpoint tests ────────────────────────────────────────────────────

def _make_upload(filename, content=b"fake-onnx-data"):
    return (io.BytesIO(content), filename)


def test_upload_valid_onnx(client, tmp_voices_dir):
    """Upload di un .onnx valido deve tornare 200 e il file deve esistere."""
    data = {"file": _make_upload("it_IT-paola-medium.onnx")}
    rv = client.post("/api/tts/offline/upload", data=data, content_type="multipart/form-data")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["status"] == "ok"
    assert body["filename"] == "it_IT-paola-medium.onnx"
    assert os.path.isfile(os.path.join(str(tmp_voices_dir), "it_IT-paola-medium.onnx"))


def test_upload_valid_onnx_json(client, tmp_voices_dir):
    """Upload di un .onnx.json valido deve tornare 200."""
    data = {"file": _make_upload("it_IT-paola-medium.onnx.json", b"{}")}
    rv = client.post("/api/tts/offline/upload", data=data, content_type="multipart/form-data")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["filename"] == "it_IT-paola-medium.onnx.json"


def test_upload_refresh_voices_list(client, tmp_voices_dir):
    """Dopo l'upload il campo 'voices' deve includere la voce caricata."""
    data = {"file": _make_upload("it_IT-paola-medium.onnx")}
    rv = client.post("/api/tts/offline/upload", data=data, content_type="multipart/form-data")
    assert rv.status_code == 200
    assert "it_IT-paola-medium" in rv.get_json()["voices"]


def test_upload_invalid_extension(client):
    """Upload con estensione non consentita deve tornare 400."""
    data = {"file": _make_upload("malicious.exe")}
    rv = client.post("/api/tts/offline/upload", data=data, content_type="multipart/form-data")
    assert rv.status_code == 400
    assert "error" in rv.get_json()


def test_upload_no_file_field(client):
    """Richiesta senza campo 'file' deve tornare 400."""
    rv = client.post("/api/tts/offline/upload", data={}, content_type="multipart/form-data")
    assert rv.status_code == 400
    assert "error" in rv.get_json()


def test_upload_empty_filename(client):
    """Upload con filename vuoto deve tornare 400."""
    data = {"file": (io.BytesIO(b"data"), "")}
    rv = client.post("/api/tts/offline/upload", data=data, content_type="multipart/form-data")
    assert rv.status_code == 400


def test_upload_path_traversal_is_safe(client, tmp_voices_dir):
    """Filename con path traversal non deve scrivere fuori dalla voices dir."""
    data = {"file": _make_upload("../../evil.onnx")}
    rv = client.post("/api/tts/offline/upload", data=data, content_type="multipart/form-data")
    # Either sanitized to a safe name (200) or rejected (400) — never a path outside voices dir
    if rv.status_code == 200:
        fname = rv.get_json()["filename"]
        assert ".." not in fname
        assert "/" not in fname
        assert "\\" not in fname
        # File must be inside the voices dir, not outside
        dest = os.path.join(str(tmp_voices_dir), fname)
        assert os.path.isfile(dest)
    else:
        assert rv.status_code == 400


# ─── AI status / key management ──────────────────────────────────────────────

def test_ai_status_openai_configured_false_when_no_key(client, monkeypatch):
    """openai_configured deve essere False quando non c'è chiave."""
    import api.ai as ai_mod
    monkeypatch.setitem(ai_mod.ai_settings, "openai_api_key", "")
    monkeypatch.setattr(ai_mod, "OPENAI_API_KEY", "")

    rv = client.get("/api/ai/status")
    assert rv.status_code == 200
    assert rv.get_json()["openai_configured"] is False


def test_ai_status_openai_configured_true_when_key_set(client, monkeypatch):
    """openai_configured deve essere True quando la chiave è impostata."""
    import api.ai as ai_mod
    monkeypatch.setitem(ai_mod.ai_settings, "openai_api_key", "sk-test-key-123456")

    rv = client.get("/api/ai/status")
    assert rv.status_code == 200
    assert rv.get_json()["openai_configured"] is True


def test_ai_settings_get_masks_key(client, monkeypatch):
    """GET /api/ai/settings non deve esporre la chiave completa."""
    import api.ai as ai_mod
    real_key = "sk-realkey1234567890abcdefghij"
    monkeypatch.setitem(ai_mod.ai_settings, "openai_api_key", real_key)

    rv = client.get("/api/ai/settings")
    assert rv.status_code == 200
    returned_key = rv.get_json().get("openai_api_key", "")
    assert real_key not in returned_key, "La chiave completa non deve essere restituita"
    assert "*" in returned_key, "La chiave deve essere mascherata con '*'"


def test_ai_settings_post_saves_key(client, monkeypatch):
    """POST /api/ai/settings deve salvare la chiave API."""
    import api.ai as ai_mod
    monkeypatch.setitem(ai_mod.ai_settings, "openai_api_key", "")

    rv = client.post("/api/ai/settings", json={"openai_api_key": "sk-newkey-test-abc"})
    assert rv.status_code == 200
    assert ai_mod.ai_settings.get("openai_api_key") == "sk-newkey-test-abc"


def test_ai_settings_post_skips_masked_key(client, monkeypatch):
    """POST /api/ai/settings NON deve sovrascrivere la chiave se contiene '*'."""
    import api.ai as ai_mod
    original = "sk-original-secret-key"
    monkeypatch.setitem(ai_mod.ai_settings, "openai_api_key", original)

    rv = client.post("/api/ai/settings", json={"openai_api_key": "sk-***-masked"})
    assert rv.status_code == 200
    assert ai_mod.ai_settings.get("openai_api_key") == original, \
        "La chiave mascherata non deve sovrascrivere quella reale"


def test_ai_settings_post_clears_key_with_empty_string(client, monkeypatch):
    """POST /api/ai/settings con chiave vuota deve rimuovere la chiave."""
    import api.ai as ai_mod
    monkeypatch.setitem(ai_mod.ai_settings, "openai_api_key", "sk-existing-key")

    rv = client.post("/api/ai/settings", json={"openai_api_key": ""})
    assert rv.status_code == 200
    assert ai_mod.ai_settings.get("openai_api_key") == ""
