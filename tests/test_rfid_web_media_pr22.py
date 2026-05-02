"""
tests/test_rfid_web_media_pr22.py — PR 22: RFID web_media unified support.

Covers:
A) VALID_MODES includes web_media
B) validate_rfid_profile(): web_media mode validation (url, content_type)
C) validate_rfid_profile(): web_media_url must be valid HTTP/HTTPS
D) validate_rfid_profile(): web_content_type defaults to 'generic' on unknown value
E) validate_rfid_profile(): missing web_media_url when mode=web_media → error
F) Backward compat: webradio, rss_feed, media_folder, ai_chat, edu_ai unaffected
G) POST /rfid/profile: create web_media profile
H) POST /rfid/trigger mode=web_media (radio/podcast/youtube/generic): calls start_player
I) POST /rfid/trigger mode=web_media content_type=rss: fetches RSS feed
J) POST /rfid/trigger mode=web_media missing url → 400
K) POST /rfid/current: exposes web_content_type and web_media_url
L) Language targets: japanese and chinese accepted for edu_ai profiles
"""

import json
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

@pytest.fixture()
def rfid_app():
    """Minimal Flask app with rfid_bp registered."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.rfid import rfid_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-web-media-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(rfid_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(rfid_app):
    with rfid_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """Reset rfid_profiles and media_runtime before each test."""
    from core.state import rfid_profiles, media_runtime, rss_runtime

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
    rss_runtime.clear()
    yield
    rfid_profiles.clear()
    media_runtime.clear()
    rss_runtime.clear()


@pytest.fixture(autouse=True)
def mock_internet_available():
    """Patch has_internet to return True so trigger tests work without real internet."""
    with patch("api.rfid.has_internet", return_value=True):
        yield


def _make_web_media_profile(rfid_code="WM:00:11:22", url="https://stream.example.com/radio.mp3",
                             content_type="radio", name="Test Radio"):
    return {
        "rfid_code": rfid_code,
        "name": name,
        "mode": "web_media",
        "web_media_url": url,
        "web_content_type": content_type,
        "volume": 75,
    }


# ---------------------------------------------------------------------------
# A) VALID_MODES
# ---------------------------------------------------------------------------

class TestValidModes:
    def test_web_media_in_valid_modes(self):
        from api.rfid import VALID_MODES
        assert "web_media" in VALID_MODES

    def test_all_legacy_modes_still_present(self):
        from api.rfid import VALID_MODES
        for m in ("media_folder", "webradio", "ai_chat", "rss_feed", "edu_ai"):
            assert m in VALID_MODES, f"Legacy mode '{m}' missing from VALID_MODES"


# ---------------------------------------------------------------------------
# B) Validation — web_media mode
# ---------------------------------------------------------------------------

class TestWebMediaValidation:
    def test_valid_web_media_radio(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile()
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["mode"] == "web_media"
        assert profile["web_media_url"] == "https://stream.example.com/radio.mp3"
        assert profile["web_content_type"] == "radio"

    def test_valid_web_media_youtube(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile(
            url="https://www.youtube.com/watch?v=examplevideo1",
            content_type="youtube",
        )
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["web_content_type"] == "youtube"

    def test_valid_web_media_podcast(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile(
            url="https://podcast.example.com/ep1.mp3",
            content_type="podcast",
        )
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["web_content_type"] == "podcast"

    def test_valid_web_media_rss(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile(
            url="https://feeds.example.com/podcast.xml",
            content_type="rss",
        )
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["web_content_type"] == "rss"

    def test_valid_web_media_generic(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile(
            url="https://media.example.com/audio.ogg",
            content_type="generic",
        )
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["web_content_type"] == "generic"

    # C) web_media_url must be valid HTTP
    def test_invalid_url_not_http(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile(url="ftp://example.com/file.mp3")
        profile, err = validate_rfid_profile(data)
        assert err is not None
        assert "web_media_url" in err.lower()

    def test_invalid_url_not_url(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile(url="not-a-url")
        profile, err = validate_rfid_profile(data)
        assert err is not None

    # D) unknown content_type defaults to generic
    def test_unknown_content_type_defaults_to_generic(self):
        from api.rfid import validate_rfid_profile
        data = _make_web_media_profile(content_type="music_video_crazy")
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["web_content_type"] == "generic"

    # E) missing web_media_url → error
    def test_missing_web_media_url(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "WM:AA:BB:CC",
            "name": "Missing URL",
            "mode": "web_media",
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None
        assert "web_media_url" in err.lower()


# ---------------------------------------------------------------------------
# F) Backward compat — existing modes unaffected
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_webradio_still_valid(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "WR:00:11:22",
            "name": "Legacy Radio",
            "mode": "webradio",
            "webradio_url": "http://icestreaming.rai.it/1.mp3",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["mode"] == "webradio"
        assert profile["webradio_url"] == "http://icestreaming.rai.it/1.mp3"

    def test_rss_feed_still_valid(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "RS:00:11:22",
            "name": "Legacy RSS",
            "mode": "rss_feed",
            "rss_url": "https://feeds.example.com/news.xml",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["mode"] == "rss_feed"

    def test_media_folder_still_valid(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "MF:00:11:22",
            "name": "Legacy Folder",
            "mode": "media_folder",
            "folder": "/home/gufobox/media/storie",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["mode"] == "media_folder"

    def test_ai_chat_still_valid(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AI:00:11:22",
            "name": "Legacy AI",
            "mode": "ai_chat",
            "ai_prompt": "Sei un gufo",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["mode"] == "ai_chat"


# ---------------------------------------------------------------------------
# G) POST /rfid/profile — create web_media profile
# ---------------------------------------------------------------------------

class TestCreateWebMediaProfile:
    def test_create_web_media_profile(self, client):
        with patch("api.rfid.save_json_direct"):
            resp = client.post(
                "/api/rfid/profile",
                json=_make_web_media_profile(),
                content_type="application/json",
            )
        assert resp.status_code == 201
        body = json.loads(resp.data)
        assert body["status"] == "ok"
        assert body["profile"]["mode"] == "web_media"
        assert body["profile"]["web_media_url"] == "https://stream.example.com/radio.mp3"
        assert body["profile"]["web_content_type"] == "radio"

    def test_create_web_media_youtube_profile(self, client):
        with patch("api.rfid.save_json_direct"):
            resp = client.post(
                "/api/rfid/profile",
                json=_make_web_media_profile(
                    rfid_code="YT:00:11:22",
                    url="https://www.youtube.com/watch?v=test123",
                    content_type="youtube",
                    name="YouTube Video",
                ),
                content_type="application/json",
            )
        assert resp.status_code == 201
        body = json.loads(resp.data)
        assert body["profile"]["web_content_type"] == "youtube"

    def test_create_web_media_missing_url_returns_400(self, client):
        with patch("api.rfid.save_json_direct"):
            resp = client.post(
                "/api/rfid/profile",
                json={"rfid_code": "XX:00:11:22", "name": "No URL", "mode": "web_media"},
                content_type="application/json",
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# H) POST /rfid/trigger mode=web_media (radio/podcast/youtube/generic)
# ---------------------------------------------------------------------------

class TestTriggerWebMedia:
    def _seed_profile(self, rfid_code, url, content_type):
        from core.state import rfid_profiles
        rfid_profiles[rfid_code] = {
            "rfid_code": rfid_code,
            "name": "Web Test",
            "enabled": True,
            "mode": "web_media",
            "web_media_url": url,
            "web_content_type": content_type,
            "volume": 70,
            "led": None,
        }

    @pytest.mark.parametrize("content_type", ["radio", "podcast", "youtube", "generic"])
    def test_trigger_media_types_call_start_player(self, client, content_type):
        code = f"WM:{content_type[:2].upper()}:11:22"
        url = "https://media.example.com/stream.mp3"
        self._seed_profile(code, url, content_type)

        mock_result = (True, "ok")
        with patch("core.media.start_player", return_value=mock_result) as mock_player, \
             patch("api.rfid._apply_profile_led"):
            resp = client.post(
                "/api/rfid/trigger",
                json={"rfid_code": code},
                content_type="application/json",
            )

        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body["status"] == "ok"
        assert body["mode"] == "web_media"
        assert body["web_content_type"] == content_type
        assert body["url"] == url
        mock_player.assert_called_once()
        call_args = mock_player.call_args
        assert call_args[0][0] == url

    def test_trigger_radio_updates_media_runtime(self, client):
        code = "WM:RA:11:22"
        url = "https://stream.example.com/radio.mp3"
        self._seed_profile(code, url, "radio")

        with patch("core.media.start_player", return_value=(True, "ok")), \
             patch("api.rfid._apply_profile_led"):
            client.post("/api/rfid/trigger", json={"rfid_code": code},
                        content_type="application/json")

        from core.state import media_runtime
        assert media_runtime["current_mode"] == "web_media"
        assert media_runtime["web_content_type"] == "radio"
        assert media_runtime["web_media_url"] == url

    def test_trigger_start_player_failure_returns_500(self, client):
        code = "WM:FL:11:22"
        self._seed_profile(code, "https://example.com/fail.mp3", "generic")

        with patch("core.media.start_player", return_value=(False, "player error")), \
             patch("api.rfid._apply_profile_led"):
            resp = client.post("/api/rfid/trigger", json={"rfid_code": code},
                               content_type="application/json")

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# I) POST /rfid/trigger mode=web_media content_type=rss
# ---------------------------------------------------------------------------

class TestTriggerWebMediaRss:
    def _seed_rss_profile(self, code="WM:RS:11:22"):
        from core.state import rfid_profiles
        rfid_profiles[code] = {
            "rfid_code": code,
            "name": "Web RSS",
            "enabled": True,
            "mode": "web_media",
            "web_media_url": "https://feeds.example.com/podcast.xml",
            "web_content_type": "rss",
            "rss_limit": 5,
            "volume": 70,
            "led": None,
        }
        return code

    def test_trigger_rss_fetches_feed(self, client):
        code = self._seed_rss_profile()
        mock_items = [{"title": "Ep 1", "link": "https://ex.com/1", "summary": "...", "published": "2024-01-01"}]

        with patch("api.rfid._fetch_rss", return_value=(mock_items, None)) as mock_fetch, \
             patch("api.rfid._apply_profile_led"):
            resp = client.post("/api/rfid/trigger", json={"rfid_code": code},
                               content_type="application/json")

        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body["status"] == "ok"
        assert body["mode"] == "web_media"
        assert body["web_content_type"] == "rss"
        assert len(body["items"]) == 1
        mock_fetch.assert_called_once()

    def test_trigger_rss_stores_in_rss_runtime(self, client):
        code = self._seed_rss_profile()
        mock_items = [{"title": "Ep 1", "link": "https://ex.com/1"}]

        with patch("api.rfid._fetch_rss", return_value=(mock_items, None)), \
             patch("api.rfid._apply_profile_led"):
            client.post("/api/rfid/trigger", json={"rfid_code": code},
                        content_type="application/json")

        from core.state import rss_runtime
        assert code in rss_runtime
        assert rss_runtime[code]["rss_url"] == "https://feeds.example.com/podcast.xml"

    def test_trigger_rss_fetch_error_returns_500(self, client):
        code = self._seed_rss_profile()

        with patch("api.rfid._fetch_rss", return_value=(None, "network error")), \
             patch("api.rfid._apply_profile_led"):
            resp = client.post("/api/rfid/trigger", json={"rfid_code": code},
                               content_type="application/json")

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# J) Missing URL in trigger → 400
# ---------------------------------------------------------------------------

class TestTriggerMissingUrl:
    def test_trigger_web_media_no_url_returns_400(self, client):
        from core.state import rfid_profiles
        code = "WM:NU:11:22"
        rfid_profiles[code] = {
            "rfid_code": code,
            "name": "No URL",
            "enabled": True,
            "mode": "web_media",
            "web_media_url": "",  # empty
            "web_content_type": "radio",
            "volume": 70,
            "led": None,
        }

        with patch("api.rfid._apply_profile_led"):
            resp = client.post("/api/rfid/trigger", json={"rfid_code": code},
                               content_type="application/json")

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# K) GET /rfid/current exposes web_content_type and web_media_url
# ---------------------------------------------------------------------------

class TestRfidCurrentWebMedia:
    def test_current_exposes_web_fields(self, client):
        from core.state import media_runtime
        media_runtime["current_rfid"] = "WM:00:11:22"
        media_runtime["current_profile_name"] = "My Radio"
        media_runtime["current_mode"] = "web_media"
        media_runtime["web_content_type"] = "radio"
        media_runtime["web_media_url"] = "https://stream.example.com/radio.mp3"

        resp = client.get("/api/rfid/current")
        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body["current_mode"] == "web_media"
        assert body["web_content_type"] == "radio"
        assert body["web_media_url"] == "https://stream.example.com/radio.mp3"

    def test_current_web_fields_none_when_not_web_media(self, client):
        from core.state import media_runtime
        media_runtime["current_rfid"] = None
        resp = client.get("/api/rfid/current")
        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body.get("web_content_type") is None
        assert body.get("web_media_url") is None


# ---------------------------------------------------------------------------
# L) Japanese and Chinese language targets for edu_ai
# ---------------------------------------------------------------------------

class TestLanguageTargetExpansion:
    @pytest.mark.parametrize("lang", ["japanese", "chinese"])
    def test_new_languages_valid_in_rfid_profile(self, lang):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": f"ED:{lang[:2].upper()}:11:22",
            "name": f"Lingue {lang}",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "bambino",
                "activity_mode": "foreign_languages",
                "language_target": lang,
                "learning_step": 1,
            },
        }
        profile, err = validate_rfid_profile(data)
        assert err is None, f"Expected no error for language '{lang}', got: {err}"
        assert profile["edu_config"]["language_target"] == lang

    @pytest.mark.parametrize("lang", ["japanese", "chinese"])
    def test_new_languages_valid_in_ai_module(self, lang):
        from api.ai import VALID_LANGUAGE_TARGETS, LANGUAGE_NAMES_IT
        assert lang in VALID_LANGUAGE_TARGETS
        assert lang in LANGUAGE_NAMES_IT

    def test_old_languages_still_valid(self):
        from api.rfid import _VALID_LANGUAGE_TARGETS
        for lang in ("english", "spanish", "german", "french"):
            assert lang in _VALID_LANGUAGE_TARGETS

    def test_apply_rfid_edu_config_accepts_japanese(self):
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({
            "age_group": "ragazzo",
            "activity_mode": "foreign_languages",
            "language_target": "japanese",
            "learning_step": 2,
        })
        assert ai_settings["language_target"] == "japanese"

    def test_apply_rfid_edu_config_accepts_chinese(self):
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({
            "age_group": "bambino",
            "activity_mode": "foreign_languages",
            "language_target": "chinese",
            "learning_step": 1,
        })
        assert ai_settings["language_target"] == "chinese"
