"""
tests/test_rfid_edu_ai_pr21.py — PR 21: RFID ↔ Educational AI integration.

Covers:
A) _validate_edu_config_block(): valid, invalid, activities list passthrough
B) validate_rfid_profile(): edu_ai mode validation, backward compat
C) POST /rfid/profile: create edu_ai profiles, missing edu_config defaults
D) PUT /rfid/profile: update edu_ai profiles
E) POST /rfid/trigger mode=edu_ai: applies edu_config to ai_settings
F) POST /rfid/trigger mode=edu_ai: chat history reset
G) POST /rfid/trigger mode=edu_ai: invalid edu_config returns 400
H) POST /rfid/trigger mode=edu_ai: missing edu_config returns 400
I) Backward compat: existing modes (media_folder, webradio, ai_chat, rss_feed) unaffected
J) apply_rfid_edu_config(): applies correct values, fallback on invalid
K) GET /ai/status: exposes active_rfid, active_profile_name, edu_rfid_active
L) Event log: edu_ai activation is logged
M) VALID_MODES includes edu_ai
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
    """Minimal Flask app with rfid_bp and ai_bp registered."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.rfid import rfid_bp
    from api.ai import ai_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-rfid-edu-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(rfid_bp, url_prefix="/api")
    flask_app.register_blueprint(ai_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(rfid_app):
    with rfid_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """Reset rfid_profiles, ai_runtime and ai_settings before each test."""
    from core.state import rfid_profiles, ai_runtime, DEFAULT_AI_RUNTIME
    from api.ai import ai_settings

    rfid_profiles.clear()
    ai_runtime.clear()
    ai_runtime.update(deepcopy(DEFAULT_AI_RUNTIME))

    ai_settings.update({
        "age_group": "bambino",
        "activity_mode": "free_conversation",
        "language_target": "english",
        "learning_step": 1,
        "tts_provider": "browser",
        "temperature": 0.7,
        "model": "gpt-3.5-turbo",
        "system_prompt": "Sei il Gufetto Magico.",
        "openai_api_key": "",
    })
    yield
    rfid_profiles.clear()


@pytest.fixture()
def tmp_files(tmp_path):
    """Patch file paths to temp files so tests don't hit the real filesystem."""
    rfid_f = str(tmp_path / "rfid_profiles.json")
    ai_f = str(tmp_path / "ai_settings.json")
    event_f = str(tmp_path / "events.jsonl")

    import api.rfid as _rfid_mod
    import api.ai as _ai_mod
    import core.event_log as _el

    orig_rfid = _rfid_mod.RFID_PROFILES_FILE
    orig_ai = _ai_mod.AI_SETTINGS_FILE
    orig_el = _el._log_file

    _rfid_mod.RFID_PROFILES_FILE = rfid_f
    _ai_mod.AI_SETTINGS_FILE = ai_f
    _el._log_file = event_f

    yield {"rfid": rfid_f, "ai": ai_f, "events": event_f}

    _rfid_mod.RFID_PROFILES_FILE = orig_rfid
    _ai_mod.AI_SETTINGS_FILE = orig_ai
    _el._log_file = orig_el


# ---------------------------------------------------------------------------
# A) _validate_edu_config_block
# ---------------------------------------------------------------------------

class TestValidateEduConfigBlock:
    def test_valid_config(self):
        from api.rfid import _validate_edu_config_block
        cfg, err = _validate_edu_config_block({
            "age_group": "bambino",
            "activity_mode": "foreign_languages",
            "language_target": "english",
            "learning_step": 3,
        })
        assert err is None
        assert cfg["age_group"] == "bambino"
        assert cfg["activity_mode"] == "foreign_languages"
        assert cfg["language_target"] == "english"
        assert cfg["learning_step"] == 3

    def test_all_age_groups(self):
        from api.rfid import _validate_edu_config_block
        for ag in ("bambino", "ragazzo", "adulto"):
            cfg, err = _validate_edu_config_block({"age_group": ag, "activity_mode": "quiz"})
            assert err is None, f"Failed for age_group={ag}: {err}"
            assert cfg["age_group"] == ag

    def test_all_activity_modes(self):
        from api.rfid import _validate_edu_config_block
        modes = ["teaching_general", "quiz", "math", "animal_sounds_games",
                 "interactive_story", "foreign_languages", "free_conversation"]
        for m in modes:
            cfg, err = _validate_edu_config_block({"age_group": "ragazzo", "activity_mode": m})
            assert err is None, f"Failed for activity_mode={m}: {err}"

    def test_invalid_age_group(self):
        from api.rfid import _validate_edu_config_block
        cfg, err = _validate_edu_config_block({"age_group": "neonato", "activity_mode": "quiz"})
        assert err is not None
        assert "age_group" in err

    def test_invalid_activity_mode(self):
        from api.rfid import _validate_edu_config_block
        cfg, err = _validate_edu_config_block({"age_group": "bambino", "activity_mode": "cooking"})
        assert err is not None
        assert "activity_mode" in err

    def test_foreign_languages_requires_valid_language_target(self):
        from api.rfid import _validate_edu_config_block
        cfg, err = _validate_edu_config_block({
            "age_group": "bambino",
            "activity_mode": "foreign_languages",
            "language_target": "klingon",
        })
        assert err is not None
        assert "language_target" in err

    def test_all_language_targets(self):
        from api.rfid import _validate_edu_config_block
        for lang in ("english", "spanish", "german", "french"):
            cfg, err = _validate_edu_config_block({
                "age_group": "adulto",
                "activity_mode": "foreign_languages",
                "language_target": lang,
            })
            assert err is None, f"Failed for language_target={lang}: {err}"

    def test_learning_step_defaults_to_1(self):
        from api.rfid import _validate_edu_config_block
        cfg, err = _validate_edu_config_block({"age_group": "bambino", "activity_mode": "quiz"})
        assert err is None
        assert cfg["learning_step"] == 1

    def test_none_returns_none_no_error(self):
        from api.rfid import _validate_edu_config_block
        cfg, err = _validate_edu_config_block(None)
        assert cfg is None
        assert err is None

    def test_non_dict_returns_error(self):
        from api.rfid import _validate_edu_config_block
        cfg, err = _validate_edu_config_block("not a dict")
        assert err is not None
        assert cfg is None

    def test_activities_list_passthrough(self):
        """Future multi-activity list is stored as-is for forward compat."""
        from api.rfid import _validate_edu_config_block
        acts = [{"activity_mode": "quiz"}, {"activity_mode": "math"}]
        cfg, err = _validate_edu_config_block({
            "age_group": "ragazzo",
            "activity_mode": "quiz",
            "activities": acts,
        })
        assert err is None
        assert cfg["activities"] == acts


# ---------------------------------------------------------------------------
# B) validate_rfid_profile — edu_ai mode
# ---------------------------------------------------------------------------

class TestValidateRfidProfileEduAi:
    def test_valid_edu_ai_profile(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB:CC:DD",
            "name": "Statuetta Inglese",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "bambino",
                "activity_mode": "foreign_languages",
                "language_target": "english",
                "learning_step": 1,
            },
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["mode"] == "edu_ai"
        assert profile["edu_config"]["age_group"] == "bambino"
        assert profile["edu_config"]["activity_mode"] == "foreign_languages"

    def test_edu_ai_missing_edu_config_gets_defaults(self):
        """When edu_config is omitted for mode=edu_ai, defaults are applied."""
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB:CC:01",
            "name": "Test",
            "mode": "edu_ai",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["edu_config"] is not None
        assert profile["edu_config"]["age_group"] == "bambino"

    def test_edu_ai_invalid_edu_config_returns_error(self):
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB:CC:02",
            "name": "Bad edu",
            "mode": "edu_ai",
            "edu_config": {"age_group": "neonato", "activity_mode": "cooking"},
        }
        profile, err = validate_rfid_profile(data)
        assert err is not None

    def test_edu_config_none_for_non_edu_modes(self):
        """Non-edu modes produce profile with edu_config=None."""
        from api.rfid import validate_rfid_profile
        data = {
            "rfid_code": "AA:BB:CC:03",
            "name": "Media",
            "mode": "media_folder",
            "folder": "/home/media",
        }
        profile, err = validate_rfid_profile(data)
        assert err is None
        assert profile["edu_config"] is None


# ---------------------------------------------------------------------------
# C) POST /rfid/profile — create edu_ai
# ---------------------------------------------------------------------------

class TestCreateEduAiProfile:
    def test_create_edu_ai_profile(self, client, tmp_files):
        r = client.post("/api/rfid/profile", json={
            "rfid_code": "ED:00:00:01",
            "name": "Statuetta Inglese Bambino",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "bambino",
                "activity_mode": "foreign_languages",
                "language_target": "english",
                "learning_step": 1,
            },
        })
        assert r.status_code == 201
        body = r.get_json()
        assert body["profile"]["mode"] == "edu_ai"
        assert body["profile"]["edu_config"]["age_group"] == "bambino"

    def test_create_edu_ai_quiz_profile(self, client, tmp_files):
        r = client.post("/api/rfid/profile", json={
            "rfid_code": "ED:00:00:02",
            "name": "Quiz Leone",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "ragazzo",
                "activity_mode": "quiz",
            },
        })
        assert r.status_code == 201
        body = r.get_json()
        assert body["profile"]["edu_config"]["activity_mode"] == "quiz"

    def test_create_edu_ai_invalid_config(self, client, tmp_files):
        r = client.post("/api/rfid/profile", json={
            "rfid_code": "ED:00:00:03",
            "name": "Bad Profile",
            "mode": "edu_ai",
            "edu_config": {"age_group": "alien"},
        })
        assert r.status_code == 400

    def test_create_legacy_modes_still_work(self, client, tmp_files):
        for mode, extra in [
            ("media_folder", {"folder": "/media"}),
            ("webradio", {"webradio_url": "http://radio.example.com/stream"}),
            ("ai_chat", {}),
        ]:
            code = f"LE:{mode[:2].upper()}:00:01"
            r = client.post("/api/rfid/profile", json={
                "rfid_code": code,
                "name": f"Legacy {mode}",
                "mode": mode,
                **extra,
            })
            assert r.status_code == 201, f"{mode} failed: {r.get_json()}"
            body = r.get_json()
            assert body["profile"]["edu_config"] is None


# ---------------------------------------------------------------------------
# D) PUT /rfid/profile — update edu_ai
# ---------------------------------------------------------------------------

class TestUpdateEduAiProfile:
    def test_update_edu_config(self, client, tmp_files):
        # Create
        client.post("/api/rfid/profile", json={
            "rfid_code": "UP:00:00:01",
            "name": "Orig",
            "mode": "edu_ai",
            "edu_config": {"age_group": "bambino", "activity_mode": "quiz"},
        })
        # Update
        r = client.put("/api/rfid/profile/UP:00:00:01", json={
            "rfid_code": "UP:00:00:01",
            "name": "Updated",
            "mode": "edu_ai",
            "edu_config": {"age_group": "ragazzo", "activity_mode": "math", "learning_step": 2},
        })
        assert r.status_code == 200
        body = r.get_json()
        assert body["profile"]["edu_config"]["age_group"] == "ragazzo"
        assert body["profile"]["edu_config"]["learning_step"] == 2

    def test_update_with_invalid_edu_config(self, client, tmp_files):
        client.post("/api/rfid/profile", json={
            "rfid_code": "UP:00:00:02",
            "name": "Test",
            "mode": "edu_ai",
            "edu_config": {"age_group": "bambino", "activity_mode": "quiz"},
        })
        r = client.put("/api/rfid/profile/UP:00:00:02", json={
            "rfid_code": "UP:00:00:02",
            "name": "Test",
            "mode": "edu_ai",
            "edu_config": {"age_group": "neonato"},
        })
        assert r.status_code == 400

    def test_update_without_edu_config_preserves_existing(self, client, tmp_files):
        """PUT without edu_config should preserve the existing edu_config (via merge)."""
        client.post("/api/rfid/profile", json={
            "rfid_code": "UP:00:00:03",
            "name": "Orig",
            "mode": "edu_ai",
            "edu_config": {"age_group": "adulto", "activity_mode": "math", "learning_step": 3},
        })
        # Update only the name, no edu_config in payload
        r = client.put("/api/rfid/profile/UP:00:00:03", json={
            "rfid_code": "UP:00:00:03",
            "name": "Renamed",
        })
        assert r.status_code == 200
        body = r.get_json()
        # edu_config from existing profile should be preserved via server-side merge
        assert body["profile"]["edu_config"]["age_group"] == "adulto"
        assert body["profile"]["edu_config"]["activity_mode"] == "math"
        assert body["profile"]["edu_config"]["learning_step"] == 3


# ---------------------------------------------------------------------------
# E) POST /rfid/trigger mode=edu_ai — applies edu_config
# ---------------------------------------------------------------------------

class TestTriggerEduAi:
    def _create_edu_profile(self, rfid_code="ED:TR:00:01", age_group="bambino",
                            activity_mode="foreign_languages", language_target="english",
                            learning_step=1, name="Test Edu"):
        from core.state import rfid_profiles
        import time
        rfid_profiles[rfid_code] = {
            "rfid_code": rfid_code,
            "name": name,
            "enabled": True,
            "mode": "edu_ai",
            "edu_config": {
                "age_group": age_group,
                "activity_mode": activity_mode,
                "language_target": language_target,
                "learning_step": learning_step,
            },
            "led": None,
            "updated_at": int(time.time()),
        }

    def test_trigger_applies_edu_config_to_ai_settings(self, client, tmp_files):
        self._create_edu_profile(age_group="ragazzo", activity_mode="quiz")
        r = client.post("/api/rfid/trigger", json={"rfid_code": "ED:TR:00:01"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["status"] == "ok"
        assert body["mode"] == "edu_ai"
        assert body["edu_config"]["age_group"] == "ragazzo"
        assert body["edu_config"]["activity_mode"] == "quiz"

        from api.ai import ai_settings
        assert ai_settings["age_group"] == "ragazzo"
        assert ai_settings["activity_mode"] == "quiz"

    def test_trigger_applies_foreign_languages(self, client, tmp_files):
        self._create_edu_profile(
            rfid_code="ED:TR:00:02",
            age_group="bambino",
            activity_mode="foreign_languages",
            language_target="spanish",
            learning_step=2,
        )
        r = client.post("/api/rfid/trigger", json={"rfid_code": "ED:TR:00:02"})
        assert r.status_code == 200

        from api.ai import ai_settings
        assert ai_settings["age_group"] == "bambino"
        assert ai_settings["activity_mode"] == "foreign_languages"
        assert ai_settings["language_target"] == "spanish"
        assert ai_settings["learning_step"] == 2

    def test_trigger_sets_active_rfid_in_runtime(self, client, tmp_files):
        self._create_edu_profile(name="Statuetta Bosco", age_group="bambino",
                                 activity_mode="interactive_story")
        client.post("/api/rfid/trigger", json={"rfid_code": "ED:TR:00:01"})

        from core.state import ai_runtime
        assert ai_runtime["active_rfid"] == "ED:TR:00:01"
        assert ai_runtime["active_profile_name"] == "Statuetta Bosco"
        assert ai_runtime["edu_rfid_active"] is True

    def test_trigger_resets_chat_history(self, client, tmp_files):
        """Chat history must be cleared on edu_ai trigger to avoid session mismatch."""
        from core.state import ai_runtime
        ai_runtime["history"] = [
            {"role": "user", "content": "Ciao"},
            {"role": "assistant", "content": "Ciao!"},
        ]
        self._create_edu_profile()
        client.post("/api/rfid/trigger", json={"rfid_code": "ED:TR:00:01"})
        assert ai_runtime["history"] == []

    def test_trigger_updates_media_runtime(self, client, tmp_files):
        self._create_edu_profile()
        client.post("/api/rfid/trigger", json={"rfid_code": "ED:TR:00:01"})

        from core.state import media_runtime
        assert media_runtime["current_rfid"] == "ED:TR:00:01"
        assert media_runtime["current_mode"] == "edu_ai"

    def test_trigger_edu_ai_all_modes(self, client, tmp_files):
        """Each activity_mode can be set via RFID trigger."""
        from core.state import rfid_profiles
        import time
        modes = ["teaching_general", "quiz", "math", "animal_sounds_games",
                 "interactive_story", "free_conversation"]
        for i, mode in enumerate(modes):
            code = f"ED:TM:{i:02d}:01"
            rfid_profiles[code] = {
                "rfid_code": code, "name": mode, "enabled": True,
                "mode": "edu_ai",
                "edu_config": {"age_group": "ragazzo", "activity_mode": mode,
                               "language_target": "english", "learning_step": 1},
                "led": None, "updated_at": int(time.time()),
            }
            r = client.post("/api/rfid/trigger", json={"rfid_code": code})
            assert r.status_code == 200, f"Failed for mode={mode}"
            from api.ai import ai_settings
            assert ai_settings["activity_mode"] == mode, f"ai_settings not updated for mode={mode}"


# ---------------------------------------------------------------------------
# F) POST /rfid/trigger — missing edu_config
# ---------------------------------------------------------------------------

class TestTriggerEduAiMissingConfig:
    def test_missing_edu_config_returns_400(self, client, tmp_files):
        from core.state import rfid_profiles
        import time
        rfid_profiles["ED:NO:00:01"] = {
            "rfid_code": "ED:NO:00:01", "name": "Bad", "enabled": True,
            "mode": "edu_ai", "edu_config": None,
            "led": None, "updated_at": int(time.time()),
        }
        r = client.post("/api/rfid/trigger", json={"rfid_code": "ED:NO:00:01"})
        assert r.status_code == 400
        assert "edu_config" in r.get_json().get("error", "")

    def test_disabled_profile_not_triggered(self, client, tmp_files):
        from core.state import rfid_profiles
        import time
        rfid_profiles["ED:DIS:00:01"] = {
            "rfid_code": "ED:DIS:00:01", "name": "Disabled", "enabled": False,
            "mode": "edu_ai",
            "edu_config": {"age_group": "bambino", "activity_mode": "quiz"},
            "led": None, "updated_at": int(time.time()),
        }
        r = client.post("/api/rfid/trigger", json={"rfid_code": "ED:DIS:00:01"})
        assert r.status_code == 200
        assert r.get_json()["status"] == "disabled"


# ---------------------------------------------------------------------------
# G) Backward compatibility — existing modes unaffected
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_media_folder_trigger_still_works(self, client, tmp_files):
        from core.state import rfid_profiles
        import time
        rfid_profiles["BK:MF:00:01"] = {
            "rfid_code": "BK:MF:00:01", "name": "Media", "enabled": True,
            "mode": "media_folder", "folder": "/tmp/media",
            "edu_config": None, "led": None, "updated_at": int(time.time()),
        }
        with patch("core.media.start_player", return_value=(False, "no files")), \
             patch("core.media.build_playlist", return_value=[]):
            r = client.post("/api/rfid/trigger", json={"rfid_code": "BK:MF:00:01"})
        # 404 because playlist is empty — that's the correct media_folder behavior
        assert r.status_code == 404

    def test_ai_chat_trigger_still_works(self, client, tmp_files):
        from core.state import rfid_profiles, ai_runtime
        import time
        rfid_profiles["BK:AI:00:01"] = {
            "rfid_code": "BK:AI:00:01", "name": "AI Chat", "enabled": True,
            "mode": "ai_chat", "ai_prompt": "Sei un pirata",
            "edu_config": None, "led": None, "updated_at": int(time.time()),
        }
        r = client.post("/api/rfid/trigger", json={"rfid_code": "BK:AI:00:01"})
        assert r.status_code == 200
        assert r.get_json()["mode"] == "ai_chat"
        assert ai_runtime["active_rfid"] == "BK:AI:00:01"
        # edu_rfid_active should NOT be set by a legacy ai_chat trigger
        assert not ai_runtime.get("edu_rfid_active", False)

    def test_existing_profiles_list_has_edu_config_field(self, client, tmp_files):
        """All profiles have edu_config key (None for non-edu modes)."""
        from core.state import rfid_profiles
        import time
        rfid_profiles["BK:LS:00:01"] = {
            "rfid_code": "BK:LS:00:01", "name": "Listed", "enabled": True,
            "mode": "webradio", "webradio_url": "http://example.com/stream",
            "edu_config": None, "led": None, "updated_at": int(time.time()),
        }
        r = client.get("/api/rfid/profiles")
        assert r.status_code == 200
        profiles = r.get_json()
        edu_profile = next((p for p in profiles if p["rfid_code"] == "BK:LS:00:01"), None)
        assert edu_profile is not None
        assert "edu_config" in edu_profile


# ---------------------------------------------------------------------------
# H) apply_rfid_edu_config()
# ---------------------------------------------------------------------------

class TestApplyRfidEduConfig:
    def test_applies_valid_config(self, tmp_files):
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({
            "age_group": "adulto",
            "activity_mode": "teaching_general",
            "language_target": "german",
            "learning_step": 5,
        })
        assert ai_settings["age_group"] == "adulto"
        assert ai_settings["activity_mode"] == "teaching_general"
        assert ai_settings["language_target"] == "german"
        assert ai_settings["learning_step"] == 5

    def test_falls_back_on_invalid_age_group(self, tmp_files):
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({"age_group": "neonato", "activity_mode": "quiz"})
        assert ai_settings["age_group"] == "bambino"

    def test_falls_back_on_invalid_activity_mode(self, tmp_files):
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({"age_group": "ragazzo", "activity_mode": "cooking"})
        assert ai_settings["activity_mode"] == "free_conversation"

    def test_falls_back_on_invalid_language_target(self, tmp_files):
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({
            "age_group": "adulto",
            "activity_mode": "foreign_languages",
            "language_target": "klingon",
        })
        assert ai_settings["language_target"] == "english"

    def test_syncs_legacy_fields(self, tmp_files):
        """apply_rfid_edu_config must also sync legacy fields like age_profile."""
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({"age_group": "ragazzo", "activity_mode": "math"})
        assert ai_settings.get("age_profile") == "ragazzo"

    def test_partial_config_uses_defaults(self, tmp_files):
        from api.ai import apply_rfid_edu_config, ai_settings
        apply_rfid_edu_config({})
        assert ai_settings["age_group"] == "bambino"
        assert ai_settings["activity_mode"] == "free_conversation"
        assert ai_settings["learning_step"] == 1


# ---------------------------------------------------------------------------
# I) GET /ai/status — exposes RFID edu fields
# ---------------------------------------------------------------------------

class TestAiStatusEduRfidFields:
    def test_status_has_rfid_fields(self, client, tmp_files):
        r = client.get("/api/ai/status")
        assert r.status_code == 200
        body = r.get_json()
        assert "active_rfid" in body
        assert "active_profile_name" in body
        assert "edu_rfid_active" in body

    def test_status_shows_active_rfid_after_trigger(self, client, tmp_files):
        from core.state import rfid_profiles, ai_runtime
        import time
        rfid_profiles["ST:00:00:01"] = {
            "rfid_code": "ST:00:00:01", "name": "Status Test", "enabled": True,
            "mode": "edu_ai",
            "edu_config": {"age_group": "bambino", "activity_mode": "quiz"},
            "led": None, "updated_at": int(time.time()),
        }
        client.post("/api/rfid/trigger", json={"rfid_code": "ST:00:00:01"})

        r = client.get("/api/ai/status")
        body = r.get_json()
        assert body["active_rfid"] == "ST:00:00:01"
        assert body["active_profile_name"] == "Status Test"
        assert body["edu_rfid_active"] is True
        assert body["age_group"] == "bambino"
        assert body["activity_mode"] == "quiz"


# ---------------------------------------------------------------------------
# J) VALID_MODES includes edu_ai
# ---------------------------------------------------------------------------

class TestValidModes:
    def test_edu_ai_in_valid_modes(self):
        from api.rfid import VALID_MODES
        assert "edu_ai" in VALID_MODES

    def test_all_legacy_modes_still_in_valid_modes(self):
        from api.rfid import VALID_MODES
        for m in ("media_folder", "webradio", "ai_chat", "rss_feed"):
            assert m in VALID_MODES


# ---------------------------------------------------------------------------
# K) Event logging
# ---------------------------------------------------------------------------

class TestEventLogging:
    def test_edu_ai_trigger_logs_event(self, client, tmp_files):
        from core.state import rfid_profiles
        import time
        rfid_profiles["EL:00:00:01"] = {
            "rfid_code": "EL:00:00:01", "name": "Log Test", "enabled": True,
            "mode": "edu_ai",
            "edu_config": {"age_group": "bambino", "activity_mode": "quiz"},
            "led": None, "updated_at": int(time.time()),
        }
        client.post("/api/rfid/trigger", json={"rfid_code": "EL:00:00:01"})

        from core.event_log import get_events
        events = get_events(20)
        rfid_events = [e for e in events if e.get("area") == "rfid"]
        assert len(rfid_events) > 0
        activation = next(
            (e for e in rfid_events if "AI educativa" in e.get("message", "")), None
        )
        assert activation is not None
        assert activation["details"]["rfid_code"] == "EL:00:00:01"
        assert activation["details"]["activity_mode"] == "quiz"

    def test_missing_edu_config_logs_warning(self, client, tmp_files):
        from core.state import rfid_profiles
        import time
        rfid_profiles["EL:00:00:02"] = {
            "rfid_code": "EL:00:00:02", "name": "No config", "enabled": True,
            "mode": "edu_ai", "edu_config": None,
            "led": None, "updated_at": int(time.time()),
        }
        client.post("/api/rfid/trigger", json={"rfid_code": "EL:00:00:02"})

        from core.event_log import get_events
        events = get_events(20)
        warn = next(
            (e for e in events if e.get("severity") in ("warning", "error")
             and "edu_config" in e.get("message", "")),
            None,
        )
        assert warn is not None


# ---------------------------------------------------------------------------
# L) Full round-trip integration
# ---------------------------------------------------------------------------

class TestFullRoundTrip:
    """End-to-end: create edu_ai profile → trigger → verify ai_settings."""

    def test_inglese_facile_bambino_step1(self, client, tmp_files):
        """Statuetta 'Inglese facile' → foreign_languages + english + bambino + step 1."""
        r = client.post("/api/rfid/profile", json={
            "rfid_code": "RT:IN:00:01",
            "name": "Inglese Facile",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "bambino",
                "activity_mode": "foreign_languages",
                "language_target": "english",
                "learning_step": 1,
            },
        })
        assert r.status_code == 201

        r = client.post("/api/rfid/trigger", json={"rfid_code": "RT:IN:00:01"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["edu_config"]["age_group"] == "bambino"
        assert body["edu_config"]["activity_mode"] == "foreign_languages"

        from api.ai import ai_settings
        assert ai_settings["age_group"] == "bambino"
        assert ai_settings["activity_mode"] == "foreign_languages"
        assert ai_settings["language_target"] == "english"
        assert ai_settings["learning_step"] == 1

    def test_quiz_leone_ragazzo(self, client, tmp_files):
        """Statuetta 'Quiz Leone' → quiz + ragazzo."""
        client.post("/api/rfid/profile", json={
            "rfid_code": "RT:QZ:00:01",
            "name": "Quiz Leone",
            "mode": "edu_ai",
            "edu_config": {"age_group": "ragazzo", "activity_mode": "quiz"},
        })
        r = client.post("/api/rfid/trigger", json={"rfid_code": "RT:QZ:00:01"})
        assert r.status_code == 200
        from api.ai import ai_settings
        assert ai_settings["age_group"] == "ragazzo"
        assert ai_settings["activity_mode"] == "quiz"

    def test_storia_bosco_bambino(self, client, tmp_files):
        """Statuetta 'Storia Bosco' → interactive_story + bambino."""
        client.post("/api/rfid/profile", json={
            "rfid_code": "RT:ST:00:01",
            "name": "Storia Bosco",
            "mode": "edu_ai",
            "edu_config": {"age_group": "bambino", "activity_mode": "interactive_story"},
        })
        r = client.post("/api/rfid/trigger", json={"rfid_code": "RT:ST:00:01"})
        assert r.status_code == 200
        from api.ai import ai_settings
        assert ai_settings["activity_mode"] == "interactive_story"
