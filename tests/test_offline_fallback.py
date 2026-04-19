"""
tests/test_offline_fallback.py — Test per il sistema di fallback offline (PR #34).

Copre:
  1) has_internet() con mock socket
  2) has_openai() con/senza chiave
  3) Fallback per experience_ai quando offline
  4) Fallback per ai_chat quando offline
  5) Fallback per webradio quando offline
  6) offline_folder del profilo ha priorità su OFFLINE_FALLBACK_DIR
  7) Nessun contenuto offline → notifica di errore
  8) validate_rfid_profile accetta offline_folder opzionale
  9) Mode locali (media_folder, karaoke, bedtime, voice_recording) NON usano il fallback
 10) GET /api/system/connectivity risponde con internet/openai
"""

import os
import sys
import tempfile
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _invalidate_connectivity_cache():
    """Invalida la cache di connettività prima di ogni test."""
    from core.connectivity import invalidate_cache
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture()
def app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.rfid import rfid_bp
    from api.system import system_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-offline-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(rfid_bp, url_prefix="/api")
    flask_app.register_blueprint(system_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_rfid_state():
    from core.state import rfid_profiles
    rfid_profiles.clear()
    yield
    rfid_profiles.clear()


# ---------------------------------------------------------------------------
# 1) has_internet() con mock socket
# ---------------------------------------------------------------------------

class TestHasInternet:
    def test_returns_true_when_reachable(self):
        from core.connectivity import has_internet, invalidate_cache
        invalidate_cache()
        with patch("core.connectivity.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_conn.return_value.close = MagicMock()
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            result = has_internet()
        assert result is True

    def test_returns_false_when_unreachable(self):
        from core.connectivity import has_internet, invalidate_cache
        import socket as _socket
        invalidate_cache()
        with patch("core.connectivity.socket.create_connection", side_effect=OSError("no network")):
            result = has_internet()
        assert result is False

    def test_result_is_cached(self):
        from core.connectivity import has_internet, invalidate_cache
        invalidate_cache()
        with patch("core.connectivity.socket.create_connection", side_effect=OSError("no network")):
            r1 = has_internet()
        # Second call should use cache even without mock
        r2 = has_internet()
        assert r1 is False
        assert r2 is False  # cached

    def test_invalidate_cache_clears_result(self):
        from core.connectivity import has_internet, invalidate_cache
        invalidate_cache()
        with patch("core.connectivity.socket.create_connection", side_effect=OSError):
            r1 = has_internet()
        assert r1 is False
        invalidate_cache()
        with patch("core.connectivity.socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            r2 = has_internet()
        assert r2 is True


# ---------------------------------------------------------------------------
# 2) has_openai() con/senza chiave
# ---------------------------------------------------------------------------

class TestHasOpenAI:
    def test_false_when_no_key(self):
        from core.connectivity import has_openai, invalidate_cache
        invalidate_cache()
        with patch("config.OPENAI_API_KEY", ""):
            with patch("core.connectivity.socket.create_connection") as mock_conn:
                mock_conn.return_value = MagicMock()
                result = has_openai()
        assert result is False

    def test_false_when_key_but_no_internet(self):
        from core.connectivity import has_openai, invalidate_cache
        invalidate_cache()
        with patch("config.OPENAI_API_KEY", "sk-test-key"):
            with patch("core.connectivity.socket.create_connection", side_effect=OSError):
                result = has_openai()
        assert result is False

    def test_true_when_key_and_internet(self):
        from core.connectivity import has_openai, invalidate_cache
        invalidate_cache()
        with patch("config.OPENAI_API_KEY", "sk-test-key"):
            with patch("core.connectivity.socket.create_connection") as mock_conn:
                mock_conn.return_value = MagicMock()
                result = has_openai()
        assert result is True


# ---------------------------------------------------------------------------
# 3) validate_rfid_profile accetta offline_folder opzionale
# ---------------------------------------------------------------------------

class TestValidateOfflineFolder:
    def test_offline_folder_is_optional(self):
        """Un profilo senza offline_folder è valido."""
        from api.rfid import validate_rfid_profile
        profile, err = validate_rfid_profile({
            "rfid_code": "AA:BB:CC:DD",
            "name": "Test",
            "mode": "ai_chat",
        })
        assert err is None
        assert profile["offline_folder"] == ""

    def test_offline_folder_is_stored(self):
        """offline_folder viene salvato nel profilo."""
        from api.rfid import validate_rfid_profile
        profile, err = validate_rfid_profile({
            "rfid_code": "AA:BB:CC:DD",
            "name": "Test",
            "mode": "ai_chat",
            "offline_folder": "/home/gufobox/media/offline_ai_chat",
        })
        assert err is None
        assert profile["offline_folder"] == "/home/gufobox/media/offline_ai_chat"

    def test_offline_folder_stripped(self):
        """offline_folder viene trimmed."""
        from api.rfid import validate_rfid_profile
        profile, err = validate_rfid_profile({
            "rfid_code": "AA:BB:CC:DD",
            "name": "Test",
            "mode": "webradio",
            "webradio_url": "http://radio.example.com/stream",
            "offline_folder": "  /some/path  ",
        })
        assert err is None
        assert profile["offline_folder"] == "/some/path"


# ---------------------------------------------------------------------------
# 4) _offline_fallback: profile offline_folder ha priorità su OFFLINE_FALLBACK_DIR
# ---------------------------------------------------------------------------

class TestOfflineFallbackPriority:
    def _make_profile(self, offline_folder=""):
        return {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Test Profilo",
            "mode": "ai_chat",
            "volume": 70,
            "offline_folder": offline_folder,
        }

    def test_profile_offline_folder_takes_priority(self):
        """Se profile.offline_folder è impostato, viene usato al posto di OFFLINE_FALLBACK_DIR."""
        from api.rfid import _offline_fallback

        with tempfile.TemporaryDirectory() as tmpdir:
            # Crea un file audio finto nella cartella del profilo
            audio_file = os.path.join(tmpdir, "test.mp3")
            open(audio_file, "w").close()

            profile = self._make_profile(offline_folder=tmpdir)

            with patch("api.rfid.has_internet", return_value=False):
                with patch("core.media.start_player", return_value=(True, "ok")) as mock_sp:
                    with patch("api.rfid.bus") as mock_bus:
                        ok, data = _offline_fallback("AA:BB:CC:DD", profile, "ai_chat")

            assert ok is True
            assert data["offline"] is True
            assert data["folder"] == tmpdir

    def test_default_fallback_dir_used_when_no_profile_folder(self):
        """Se offline_folder del profilo è vuoto, usa OFFLINE_FALLBACK_DIR/{mode}."""
        from api.rfid import _offline_fallback
        import config

        with tempfile.TemporaryDirectory() as tmpdir:
            mode_dir = os.path.join(tmpdir, "ai_chat")
            os.makedirs(mode_dir)
            audio_file = os.path.join(mode_dir, "fallback.mp3")
            open(audio_file, "w").close()

            profile = self._make_profile(offline_folder="")

            with patch("api.rfid.OFFLINE_FALLBACK_DIR", tmpdir):
                with patch("core.media.start_player", return_value=(True, "ok")):
                    with patch("api.rfid.bus"):
                        ok, data = _offline_fallback("AA:BB:CC:DD", profile, "ai_chat")

            assert ok is True
            assert "ai_chat" in data["folder"]


# ---------------------------------------------------------------------------
# 5) Nessun contenuto offline → notifica di errore
# ---------------------------------------------------------------------------

class TestOfflineFallbackNoContent:
    def test_no_content_emits_warning(self):
        """Quando nessun file offline è disponibile, viene emessa notifica di errore."""
        from api.rfid import _offline_fallback

        profile = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Test",
            "mode": "ai_chat",
            "volume": 70,
            "offline_folder": "",
        }

        # Empty temp dir for OFFLINE_FALLBACK_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("api.rfid.OFFLINE_FALLBACK_DIR", tmpdir):
                with patch("api.rfid.bus") as mock_bus:
                    ok, data = _offline_fallback("AA:BB:CC:DD", profile, "ai_chat")

        assert ok is False
        assert "error" in data
        mock_bus.emit_notification.assert_called()
        # Check notification level is warning
        call_args = mock_bus.emit_notification.call_args
        assert call_args[0][1] == "warning"


# ---------------------------------------------------------------------------
# 6) Fallback per experience_ai quando offline (exec layer)
# ---------------------------------------------------------------------------

class TestExperienceAIOfflineFallback:
    def test_exec_experience_ai_offline_uses_fallback(self):
        """_exec_experience_ai chiama _offline_fallback quando OpenAI non è disponibile."""
        from api.rfid import _exec_experience_ai

        profile = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Avventura",
            "mode": "adventure",
            "volume": 70,
            "offline_folder": "",
            "activity_config": {"age_group": "bambino"},
        }

        with patch("api.rfid.has_openai", return_value=False):
            with patch("api.rfid._offline_fallback", return_value=(True, {})) as mock_fb:
                result = _exec_experience_ai("AA:BB:CC:DD", profile)

        assert result is True
        mock_fb.assert_called_once_with("AA:BB:CC:DD", profile, "adventure")

    def test_exec_experience_ai_online_does_not_fallback(self):
        """_exec_experience_ai NON chiama _offline_fallback quando OpenAI è disponibile."""
        from api.rfid import _exec_experience_ai

        profile = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Avventura",
            "mode": "adventure",
            "volume": 70,
            "offline_folder": "",
            "activity_config": {"age_group": "bambino"},
        }

        with patch("api.rfid.has_openai", return_value=True):
            with patch("api.rfid._apply_experience_ai_to_runtime",
                       return_value=(True, {"age_group": "bambino", "activity_mode": "interactive_story", "icon": "🗺️"})):
                with patch("api.rfid.bus"):
                    with patch("api.rfid._offline_fallback") as mock_fb:
                        _exec_experience_ai("AA:BB:CC:DD", profile)

        mock_fb.assert_not_called()


# ---------------------------------------------------------------------------
# 7) Fallback per ai_chat quando offline (exec layer)
# ---------------------------------------------------------------------------

class TestAiChatOfflineFallback:
    def test_exec_ai_chat_offline(self):
        """_exec_ai_chat usa il fallback offline quando OpenAI non è disponibile."""
        from api.rfid import _exec_ai_chat

        profile = {"rfid_code": "AA:BB:CC:DD", "name": "Chat", "volume": 70, "offline_folder": ""}

        with patch("api.rfid.has_openai", return_value=False):
            with patch("api.rfid._offline_fallback", return_value=(False, {"error": "no content"})) as mock_fb:
                result = _exec_ai_chat("AA:BB:CC:DD", profile)

        assert result is False
        mock_fb.assert_called_once_with("AA:BB:CC:DD", profile, "ai_chat")


# ---------------------------------------------------------------------------
# 8) Fallback per webradio quando offline (exec layer)
# ---------------------------------------------------------------------------

class TestWebradioOfflineFallback:
    def test_exec_webradio_offline(self):
        """_exec_webradio usa il fallback offline quando internet non è disponibile."""
        from api.rfid import _exec_webradio

        profile = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Radio",
            "webradio_url": "http://radio.example.com/stream",
            "volume": 70,
            "offline_folder": "",
        }

        with patch("api.rfid.has_internet", return_value=False):
            with patch("api.rfid._offline_fallback", return_value=(True, {})) as mock_fb:
                result = _exec_webradio("AA:BB:CC:DD", profile)

        assert result is True
        mock_fb.assert_called_once_with("AA:BB:CC:DD", profile, "webradio")

    def test_exec_webradio_online_does_not_fallback(self):
        """_exec_webradio NON usa il fallback quando internet è disponibile."""
        from api.rfid import _exec_webradio

        profile = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Radio",
            "webradio_url": "http://radio.example.com/stream",
            "volume": 70,
            "offline_folder": "",
        }

        with patch("api.rfid.has_internet", return_value=True):
            with patch("core.media.start_player", return_value=(True, "ok")):
                with patch("api.rfid.bus"):
                    with patch("api.rfid._offline_fallback") as mock_fb:
                        _exec_webradio("AA:BB:CC:DD", profile)

        mock_fb.assert_not_called()


# ---------------------------------------------------------------------------
# 9) Mode locali NON usano il fallback (sempre funzionanti)
# ---------------------------------------------------------------------------

class TestLocalModesNoFallback:
    def test_media_folder_not_affected_by_connectivity(self):
        """_exec_media_folder non controlla la connettività."""
        from api.rfid import _exec_media_folder

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_file = os.path.join(tmpdir, "song.mp3")
            open(audio_file, "w").close()

            profile = {
                "rfid_code": "AA:BB:CC:DD",
                "name": "Musica",
                "folder": tmpdir,
                "volume": 70,
                "loop": True,
            }

            with patch("api.rfid.has_internet", return_value=False):
                with patch("api.rfid.has_openai", return_value=False):
                    with patch("core.media.start_player", return_value=(True, "ok")):
                        with patch("core.database.get_resume_position", return_value=None):
                            with patch("api.rfid.bus"):
                                with patch("api.rfid._offline_fallback") as mock_fb:
                                    _exec_media_folder("AA:BB:CC:DD", profile)

            mock_fb.assert_not_called()

    def test_voice_recording_not_affected_by_connectivity(self):
        """_exec_voice_recording non controlla la connettività."""
        from api.rfid import _exec_voice_recording

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        try:
            profile = {
                "rfid_code": "AA:BB:CC:DD",
                "name": "Registrazione",
                "recording_path": tmp_path,
                "volume": 70,
            }

            with patch("api.rfid.has_internet", return_value=False):
                with patch("api.rfid.has_openai", return_value=False):
                    with patch("core.media.start_player", return_value=(True, "ok")):
                        with patch("api.rfid.bus"):
                            with patch("api.rfid._offline_fallback") as mock_fb:
                                _exec_voice_recording("AA:BB:CC:DD", profile)

            mock_fb.assert_not_called()
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 10) GET /api/system/connectivity
# ---------------------------------------------------------------------------

class TestConnectivityEndpoint:
    def test_endpoint_returns_internet_and_openai(self, client):
        """GET /api/system/connectivity ritorna internet e openai."""
        with patch("core.connectivity.has_internet", return_value=True):
            with patch("core.connectivity.has_openai", return_value=False):
                resp = client.get("/api/system/connectivity")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "internet" in data
        assert "openai" in data

    def test_endpoint_internet_true_openai_false(self, client):
        with patch("core.connectivity.socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            with patch("config.OPENAI_API_KEY", ""):
                from core.connectivity import invalidate_cache
                invalidate_cache()
                resp = client.get("/api/system/connectivity")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["internet"] is True
        assert data["openai"] is False

    def test_endpoint_both_false_when_no_network(self, client):
        from core.connectivity import invalidate_cache
        invalidate_cache()
        with patch("core.connectivity.socket.create_connection", side_effect=OSError):
            with patch("config.OPENAI_API_KEY", "sk-key"):
                resp = client.get("/api/system/connectivity")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["internet"] is False
        assert data["openai"] is False


# ---------------------------------------------------------------------------
# 11) HTTP trigger: fallback risponde con status 503 quando offline e no content
# ---------------------------------------------------------------------------

class TestHttpTriggerFallback:
    def _create_profile(self, client, mode, extra=None):
        payload = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Test",
            "mode": mode,
        }
        if extra:
            payload.update(extra)
        resp = client.post("/api/rfid/profile", json=payload)
        return resp

    def test_trigger_webradio_offline_no_content_returns_503(self, client):
        """Se offline e nessun contenuto disponibile, trigger webradio → 503."""
        self._create_profile(client, "webradio", {
            "webradio_url": "http://radio.example.com/stream",
        })
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("api.rfid.has_internet", return_value=False):
                with patch("api.rfid.OFFLINE_FALLBACK_DIR", tmpdir):
                    resp = client.post("/api/rfid/trigger", json={"rfid_code": "AA:BB:CC:DD"})
        assert resp.status_code == 503

    def test_trigger_ai_chat_offline_no_content_returns_503(self, client):
        """Se offline e nessun contenuto disponibile, trigger ai_chat → 503."""
        self._create_profile(client, "ai_chat")
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("api.rfid.has_openai", return_value=False):
                with patch("api.rfid.OFFLINE_FALLBACK_DIR", tmpdir):
                    resp = client.post("/api/rfid/trigger", json={"rfid_code": "AA:BB:CC:DD"})
        assert resp.status_code == 503
