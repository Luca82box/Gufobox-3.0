"""
tests/test_rfid_wizard_pr24.py — PR 24: RFID category-based wizard + AI edu integration.

Covers:
A) VALID_MODES includes school and entertainment
B) validate_rfid_profile: school and entertainment modes accepted
C) POST /rfid/profile: create school and entertainment profiles
D) POST /rfid/trigger mode=school: starts wizard
E) POST /rfid/trigger mode=entertainment: starts wizard
F) Wizard state machine: start, submit, done flow (school path)
G) Wizard state machine: start, submit, done flow (entertainment path)
H) Wizard state machine: foreign_languages path (school → language → step)
I) Wizard submit: invalid answer returns error
J) Wizard cancel: resets state
K) Wizard apply_config: applies completed config to AI settings
L) POST /wizard/start: starts wizard via API
M) POST /wizard/submit: advances wizard via API, auto-applies on done
N) GET /wizard/status: returns current wizard state
O) POST /wizard/cancel: cancels wizard via API
P) school_conversation in VALID_ACTIVITY_MODES (api.ai)
Q) school_conversation in _VALID_ACTIVITY_MODES (api.rfid)
R) school_conversation in RFID edu_ai profile validation
S) GET /ai/wizard/categories: returns default categories
T) POST /ai/wizard/categories: updates categories
U) Wizard snapshot included in public snapshot
V) Legacy RFID modes (media_folder, webradio, ai_chat, rss_feed, edu_ai) still work
W) Backward compat: existing edu_ai trigger unaffected
"""
import json
import os
import sys
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def full_app():
    """Flask app with rfid_bp, ai_bp, and wizard_bp registered."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.rfid import rfid_bp
    from api.ai import ai_bp
    from api.wizard import wizard_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-wizard-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(rfid_bp, url_prefix="/api")
    flask_app.register_blueprint(ai_bp, url_prefix="/api")
    flask_app.register_blueprint(wizard_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(full_app):
    with full_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """Reset rfid_profiles, ai_runtime, ai_settings and wizard_state before each test."""
    from core.state import rfid_profiles, ai_runtime, DEFAULT_AI_RUNTIME
    from api.ai import ai_settings
    from core.wizard import wizard_state

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
    # Remove wizard_categories so each test gets fresh defaults
    ai_settings.pop("wizard_categories", None)

    wizard_state.update({
        "active": False,
        "source_category": None,
        "source_rfid": None,
        "current_stage": None,
        "partial_selection": {},
        "current_options": [],
        "completed_config": None,
        "error": None,
    })

    yield

    rfid_profiles.clear()
    wizard_state.update({
        "active": False,
        "source_category": None,
        "source_rfid": None,
        "current_stage": None,
        "partial_selection": {},
        "current_options": [],
        "completed_config": None,
        "error": None,
    })


@pytest.fixture(autouse=True)
def mock_openai_available():
    """Patch has_openai to return True so trigger tests work without a real API key."""
    with patch("api.rfid.has_openai", return_value=True):
        yield


@pytest.fixture()
def tmp_files(tmp_path):
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

    yield {"rfid": rfid_f, "ai": ai_f}

    _rfid_mod.RFID_PROFILES_FILE = orig_rfid
    _ai_mod.AI_SETTINGS_FILE = orig_ai
    _el._log_file = orig_el


# ---------------------------------------------------------------------------
# A) VALID_MODES includes school and entertainment
# ---------------------------------------------------------------------------
class TestValidModes:
    def test_school_in_valid_modes(self):
        from api.rfid import VALID_MODES
        assert "school" in VALID_MODES

    def test_entertainment_in_valid_modes(self):
        from api.rfid import VALID_MODES
        assert "entertainment" in VALID_MODES

    def test_legacy_modes_still_present(self):
        from api.rfid import VALID_MODES
        for m in ("media_folder", "webradio", "ai_chat", "rss_feed", "edu_ai", "web_media"):
            assert m in VALID_MODES


# ---------------------------------------------------------------------------
# B) validate_rfid_profile: school and entertainment
# ---------------------------------------------------------------------------
class TestValidateRfidProfileWizardModes:
    def test_school_mode_valid(self):
        from api.rfid import validate_rfid_profile
        profile, err = validate_rfid_profile({
            "rfid_code": "AA:BB:CC:01",
            "name": "Statuina Scuola",
            "mode": "school",
        })
        assert err is None
        assert profile["mode"] == "school"

    def test_entertainment_mode_valid(self):
        from api.rfid import validate_rfid_profile
        profile, err = validate_rfid_profile({
            "rfid_code": "AA:BB:CC:02",
            "name": "Statuina Intrattenimento",
            "mode": "entertainment",
        })
        assert err is None
        assert profile["mode"] == "entertainment"

    def test_school_no_edu_config_required(self):
        """school mode does not require edu_config."""
        from api.rfid import validate_rfid_profile
        profile, err = validate_rfid_profile({
            "rfid_code": "AA:BB:CC:03",
            "name": "Scuola",
            "mode": "school",
        })
        assert err is None
        assert profile.get("edu_config") is None


# ---------------------------------------------------------------------------
# C) POST /rfid/profile: create school and entertainment profiles
# ---------------------------------------------------------------------------
class TestCreateWizardProfiles:
    def test_create_school_profile(self, client, tmp_files):
        res = client.post("/api/rfid/profile", json={
            "rfid_code": "SC:00:00:01",
            "name": "Scuola Magica",
            "mode": "school",
        })
        assert res.status_code == 201
        data = res.get_json()
        assert data["profile"]["mode"] == "school"

    def test_create_entertainment_profile(self, client, tmp_files):
        res = client.post("/api/rfid/profile", json={
            "rfid_code": "EN:00:00:01",
            "name": "Giochi Magici",
            "mode": "entertainment",
        })
        assert res.status_code == 201
        data = res.get_json()
        assert data["profile"]["mode"] == "entertainment"


# ---------------------------------------------------------------------------
# D & E) POST /rfid/trigger starts wizard for school and entertainment
# ---------------------------------------------------------------------------
class TestRfidTriggerWizardModes:
    def _create_profile(self, client, rfid_code, mode, name, tmp_files):
        client.post("/api/rfid/profile", json={
            "rfid_code": rfid_code,
            "name": name,
            "mode": mode,
        })

    def test_trigger_school_starts_wizard(self, client, tmp_files):
        self._create_profile(client, "SC:11:22:33", "school", "Scuola", tmp_files)
        with patch("api.rfid.bus"):
            res = client.post("/api/rfid/trigger", json={"rfid_code": "SC:11:22:33"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["mode"] == "school"
        assert "wizard" in data
        assert data["wizard"]["active"] is True
        assert data["wizard"]["current_stage"] == "age_group"

    def test_trigger_entertainment_starts_wizard(self, client, tmp_files):
        self._create_profile(client, "EN:11:22:33", "entertainment", "Giochi", tmp_files)
        with patch("api.rfid.bus"):
            res = client.post("/api/rfid/trigger", json={"rfid_code": "EN:11:22:33"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["mode"] == "entertainment"
        assert data["wizard"]["active"] is True
        assert data["wizard"]["source_category"] == "entertainment"

    def test_trigger_school_wizard_options(self, client, tmp_files):
        """Wizard first stage offers bambino/ragazzo/adulto options."""
        self._create_profile(client, "SC:AA:BB:CC", "school", "Scuola", tmp_files)
        with patch("api.rfid.bus"):
            res = client.post("/api/rfid/trigger", json={"rfid_code": "SC:AA:BB:CC"})
        wizard = res.get_json()["wizard"]
        assert set(wizard["current_options"]) == {"bambino", "ragazzo", "adulto"}


# ---------------------------------------------------------------------------
# F) Wizard state machine: school path (no foreign_languages)
# ---------------------------------------------------------------------------
class TestWizardStateMachineSchool:
    def test_full_school_flow_teaching(self):
        from core.wizard import wizard_start, wizard_submit, STAGE_DONE

        # Start
        state = wizard_start("school", "AA:BB:CC:DD")
        assert state["active"] is True
        assert state["current_stage"] == "age_group"

        # Step 1: age
        state = wizard_submit("ragazzo")
        assert state["current_stage"] == "activity_mode"
        assert "teaching_general" in state["current_options"]

        # Step 2: activity (not foreign_languages → goes to done)
        state = wizard_submit("math")
        assert state["current_stage"] == STAGE_DONE
        assert state["active"] is False
        cfg = state["completed_config"]
        assert cfg["age_group"] == "ragazzo"
        assert cfg["activity_mode"] == "math"

    def test_school_conversation_activity_available(self):
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES
        assert "school_conversation" in CATEGORY_ACTIVITIES["school"]

        wizard_start("school")
        wizard_submit("bambino")
        from core.wizard import wizard_state
        assert "school_conversation" in wizard_state["current_options"]

    def test_school_wizard_produces_valid_config(self):
        from core.wizard import wizard_start, wizard_submit
        wizard_start("school")
        wizard_submit("adulto")
        state = wizard_submit("teaching_general")
        cfg = state["completed_config"]
        assert cfg["age_group"] == "adulto"
        assert cfg["activity_mode"] == "teaching_general"
        assert "learning_step" in cfg


# ---------------------------------------------------------------------------
# G) Wizard state machine: entertainment path
# ---------------------------------------------------------------------------
class TestWizardStateMachineEntertainment:
    def test_full_entertainment_flow(self):
        from core.wizard import wizard_start, wizard_submit, STAGE_DONE

        state = wizard_start("entertainment")
        assert state["current_stage"] == "age_group"

        state = wizard_submit("bambino")
        assert state["current_stage"] == "activity_mode"
        # Check entertainment activities
        options = state["current_options"]
        assert "quiz" in options
        assert "free_conversation" in options
        assert "animal_sounds_games" in options
        assert "interactive_story" in options

        state = wizard_submit("quiz")
        assert state["current_stage"] == STAGE_DONE
        cfg = state["completed_config"]
        assert cfg["activity_mode"] == "quiz"
        assert cfg["age_group"] == "bambino"

    def test_entertainment_no_school_activities(self):
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES
        # School activities not in entertainment
        for act in CATEGORY_ACTIVITIES["entertainment"]:
            assert act not in ("teaching_general", "math", "school_conversation")


# ---------------------------------------------------------------------------
# H) Wizard: foreign_languages full path
# ---------------------------------------------------------------------------
class TestWizardForeignLanguagesPath:
    def test_foreign_languages_asks_language(self):
        from core.wizard import wizard_start, wizard_submit, STAGE_LANGUAGE

        wizard_start("school")
        wizard_submit("ragazzo")           # age
        state = wizard_submit("foreign_languages")   # activity
        assert state["current_stage"] == STAGE_LANGUAGE
        assert "japanese" in state["current_options"]
        assert "chinese" in state["current_options"]

    def test_foreign_languages_then_step(self):
        from core.wizard import wizard_start, wizard_submit, STAGE_STEP, STAGE_DONE

        wizard_start("school")
        wizard_submit("bambino")
        wizard_submit("foreign_languages")
        state = wizard_submit("japanese")
        assert state["current_stage"] == STAGE_STEP

        state = wizard_submit("3")
        assert state["current_stage"] == STAGE_DONE
        cfg = state["completed_config"]
        assert cfg["language_target"] == "japanese"
        assert cfg["learning_step"] == 3

    def test_non_foreign_language_skips_language_stage(self):
        from core.wizard import wizard_start, wizard_submit, STAGE_DONE

        wizard_start("school")
        wizard_submit("adulto")
        state = wizard_submit("math")
        # math does not need language → goes straight to done
        assert state["current_stage"] == STAGE_DONE


# ---------------------------------------------------------------------------
# I) Wizard: invalid answer returns error
# ---------------------------------------------------------------------------
class TestWizardInvalidAnswer:
    def test_invalid_age_group_returns_error(self):
        from core.wizard import wizard_start, wizard_submit

        wizard_start("school")
        result = wizard_submit("INVALID_AGE")
        assert "error" in result

    def test_invalid_activity_returns_error(self):
        from core.wizard import wizard_start, wizard_submit

        wizard_start("entertainment")
        wizard_submit("bambino")
        result = wizard_submit("teaching_general")  # not in entertainment
        assert "error" in result

    def test_submit_without_active_wizard(self):
        from core.wizard import wizard_submit

        result = wizard_submit("bambino")
        assert "error" in result


# ---------------------------------------------------------------------------
# J) Wizard cancel
# ---------------------------------------------------------------------------
class TestWizardCancel:
    def test_cancel_resets_state(self):
        from core.wizard import wizard_start, wizard_cancel, get_wizard_state

        wizard_start("school")
        state = wizard_cancel()
        assert state["active"] is False
        assert state["current_stage"] is None
        assert state["completed_config"] is None

    def test_cancel_idempotent(self):
        from core.wizard import wizard_cancel

        state1 = wizard_cancel()
        state2 = wizard_cancel()
        assert state1["active"] is False
        assert state2["active"] is False


# ---------------------------------------------------------------------------
# K) Wizard apply_config
# ---------------------------------------------------------------------------
class TestWizardApplyConfig:
    def test_apply_config_after_completion(self):
        from core.wizard import wizard_start, wizard_submit, wizard_apply_config
        from api.ai import ai_settings

        wizard_start("school")
        wizard_submit("ragazzo")
        wizard_submit("math")
        # wizard is done now

        with patch("core.state.save_json_direct"), patch("core.state.bus"):
            success, msg = wizard_apply_config()

        assert success is True
        assert ai_settings["age_group"] == "ragazzo"
        assert ai_settings["activity_mode"] == "math"

    def test_apply_config_before_completion_fails(self):
        from core.wizard import wizard_apply_config

        success, msg = wizard_apply_config()
        assert success is False

    def test_apply_foreign_languages_config(self):
        from core.wizard import wizard_start, wizard_submit, wizard_apply_config
        from api.ai import ai_settings

        wizard_start("school")
        wizard_submit("adulto")
        wizard_submit("foreign_languages")
        wizard_submit("chinese")
        wizard_submit("5")

        with patch("core.state.save_json_direct"), patch("core.state.bus"):
            success, _ = wizard_apply_config()

        assert success is True
        assert ai_settings["activity_mode"] == "foreign_languages"
        assert ai_settings["language_target"] == "chinese"
        assert ai_settings["learning_step"] == 5


# ---------------------------------------------------------------------------
# L) POST /wizard/start
# ---------------------------------------------------------------------------
class TestWizardApiStart:
    def test_start_school(self, client):
        res = client.post("/api/wizard/start", json={"category": "school"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["wizard"]["active"] is True
        assert data["wizard"]["current_stage"] == "age_group"

    def test_start_entertainment(self, client):
        res = client.post("/api/wizard/start", json={"category": "entertainment"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["wizard"]["source_category"] == "entertainment"

    def test_start_invalid_category_returns_400(self, client):
        res = client.post("/api/wizard/start", json={"category": "invalid"})
        assert res.status_code == 400

    def test_start_missing_category_returns_400(self, client):
        res = client.post("/api/wizard/start", json={})
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# M) POST /wizard/submit
# ---------------------------------------------------------------------------
class TestWizardApiSubmit:
    def test_submit_age_advances_stage(self, client):
        client.post("/api/wizard/start", json={"category": "school"})
        res = client.post("/api/wizard/submit", json={"answer": "bambino"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["wizard"]["current_stage"] == "activity_mode"

    def test_submit_completes_wizard(self, client, tmp_files):
        client.post("/api/wizard/start", json={"category": "entertainment"})
        client.post("/api/wizard/submit", json={"answer": "adulto"})
        with patch("core.state.save_json_direct"), patch("core.state.bus"):
            res = client.post("/api/wizard/submit", json={"answer": "quiz"})
        data = res.get_json()
        assert data["status"] in ("completed", "completed_with_error")
        assert data["wizard"]["completed_config"]["activity_mode"] == "quiz"

    def test_submit_missing_answer_returns_400(self, client):
        client.post("/api/wizard/start", json={"category": "school"})
        res = client.post("/api/wizard/submit", json={})
        assert res.status_code == 400

    def test_submit_invalid_answer_returns_400(self, client):
        client.post("/api/wizard/start", json={"category": "school"})
        res = client.post("/api/wizard/submit", json={"answer": "INVALID"})
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# N) GET /wizard/status
# ---------------------------------------------------------------------------
class TestWizardApiStatus:
    def test_status_returns_wizard_state(self, client):
        res = client.get("/api/wizard/status")
        assert res.status_code == 200
        data = res.get_json()
        assert "active" in data

    def test_status_reflects_started_wizard(self, client):
        client.post("/api/wizard/start", json={"category": "entertainment"})
        res = client.get("/api/wizard/status")
        data = res.get_json()
        assert data["active"] is True
        assert data["source_category"] == "entertainment"


# ---------------------------------------------------------------------------
# O) POST /wizard/cancel
# ---------------------------------------------------------------------------
class TestWizardApiCancel:
    def test_cancel_resets_state(self, client):
        client.post("/api/wizard/start", json={"category": "school"})
        res = client.post("/api/wizard/cancel")
        assert res.status_code == 200
        data = res.get_json()
        assert data["wizard"]["active"] is False


# ---------------------------------------------------------------------------
# P) school_conversation in VALID_ACTIVITY_MODES (api.ai)
# ---------------------------------------------------------------------------
class TestSchoolConversation:
    def test_school_conversation_in_valid_activity_modes(self):
        from api.ai import VALID_ACTIVITY_MODES
        assert "school_conversation" in VALID_ACTIVITY_MODES

    def test_school_conversation_in_rfid_valid_modes(self):
        from api.rfid import _VALID_ACTIVITY_MODES
        assert "school_conversation" in _VALID_ACTIVITY_MODES

    def test_school_conversation_has_label(self):
        from api.ai import ACTIVITY_MODE_LABELS
        assert "school_conversation" in ACTIVITY_MODE_LABELS

    def test_ai_system_prompt_school_conversation(self):
        from api.ai import ai_system_prompt
        prompt = ai_system_prompt("bambino", "school_conversation")
        assert "SCOLASTICA" in prompt.upper() or "CONVERSAZIONE" in prompt.upper()

    def test_school_conversation_valid_in_edu_config(self):
        from api.rfid import _validate_edu_config_block
        result, err = _validate_edu_config_block({
            "age_group": "ragazzo",
            "activity_mode": "school_conversation",
        })
        assert err is None
        assert result["activity_mode"] == "school_conversation"


# ---------------------------------------------------------------------------
# R) school_conversation in RFID edu_ai profile
# ---------------------------------------------------------------------------
class TestSchoolConversationRfidProfile:
    def test_edu_ai_school_conversation_profile_valid(self, client, tmp_files):
        res = client.post("/api/rfid/profile", json={
            "rfid_code": "SC:CC:DD:EE",
            "name": "Conversazione Scolastica",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "ragazzo",
                "activity_mode": "school_conversation",
            },
        })
        assert res.status_code == 201
        data = res.get_json()
        assert data["profile"]["edu_config"]["activity_mode"] == "school_conversation"


# ---------------------------------------------------------------------------
# S) GET /ai/wizard/categories
# ---------------------------------------------------------------------------
class TestWizardCategoriesGet:
    def test_get_default_categories(self, client):
        res = client.get("/api/ai/wizard/categories")
        assert res.status_code == 200
        data = res.get_json()
        assert "school" in data
        assert "entertainment" in data

    def test_school_has_required_activities(self, client):
        res = client.get("/api/ai/wizard/categories")
        data = res.get_json()
        school_ids = [a["id"] for a in data["school"]["activities"]]
        assert "teaching_general" in school_ids
        assert "math" in school_ids
        assert "foreign_languages" in school_ids
        assert "school_conversation" in school_ids

    def test_entertainment_has_required_activities(self, client):
        res = client.get("/api/ai/wizard/categories")
        data = res.get_json()
        ent_ids = [a["id"] for a in data["entertainment"]["activities"]]
        assert "quiz" in ent_ids
        assert "animal_sounds_games" in ent_ids
        assert "interactive_story" in ent_ids
        assert "free_conversation" in ent_ids


# ---------------------------------------------------------------------------
# T) POST /ai/wizard/categories: updates categories
# ---------------------------------------------------------------------------
class TestWizardCategoriesPost:
    def test_post_updates_school_activities(self, client, tmp_files):
        res = client.post("/api/ai/wizard/categories", json={
            "school": {
                "activities": [
                    {"id": "teaching_general", "label": "Insegnamento", "enabled": True},
                    {"id": "math", "label": "Matematica", "enabled": False},
                ]
            }
        })
        assert res.status_code == 200
        data = res.get_json()
        school_acts = data["wizard_categories"]["school"]["activities"]
        math_act = next(a for a in school_acts if a["id"] == "math")
        assert math_act["enabled"] is False

    def test_post_invalid_category_returns_400(self, client):
        res = client.post("/api/ai/wizard/categories", json={
            "nonexistent_category": {"activities": []}
        })
        assert res.status_code == 400

    def test_post_invalid_activity_mode_returns_400(self, client):
        res = client.post("/api/ai/wizard/categories", json={
            "school": {
                "activities": [
                    {"id": "INVALID_MODE", "label": "Bad", "enabled": True},
                ]
            }
        })
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# U) Wizard snapshot in public snapshot
# ---------------------------------------------------------------------------
class TestWizardSnapshot:
    def test_wizard_in_public_snapshot(self):
        from core.state import build_public_snapshot
        from core.wizard import wizard_start

        wizard_start("school", "AA:BB:CC:DD")
        snapshot = build_public_snapshot()
        assert "wizard" in snapshot
        assert snapshot["wizard"]["active"] is True
        assert snapshot["wizard"]["source_category"] == "school"


# ---------------------------------------------------------------------------
# V) Legacy RFID modes still work
# ---------------------------------------------------------------------------
class TestLegacyModesBackwardCompat:
    def test_media_folder_profile_still_valid(self):
        from api.rfid import validate_rfid_profile
        _, err = validate_rfid_profile({
            "rfid_code": "LG:01:02:03",
            "name": "Legacy Media",
            "mode": "media_folder",
            "folder": "/tmp/media",
        })
        assert err is None

    def test_webradio_profile_still_valid(self):
        from api.rfid import validate_rfid_profile
        _, err = validate_rfid_profile({
            "rfid_code": "LG:04:05:06",
            "name": "Radio",
            "mode": "webradio",
            "webradio_url": "http://radio.example.com/stream",
        })
        assert err is None

    def test_edu_ai_profile_still_valid(self):
        from api.rfid import validate_rfid_profile
        _, err = validate_rfid_profile({
            "rfid_code": "LG:07:08:09",
            "name": "AI Edu",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "bambino",
                "activity_mode": "quiz",
            },
        })
        assert err is None


# ---------------------------------------------------------------------------
# W) edu_ai trigger backward compat
# ---------------------------------------------------------------------------
class TestEduAiTriggerBackwardCompat:
    def test_edu_ai_trigger_applies_config(self, client, tmp_files):
        from api.ai import ai_settings

        client.post("/api/rfid/profile", json={
            "rfid_code": "EDU:AA:BB:CC",
            "name": "Edu AI Compat",
            "mode": "edu_ai",
            "edu_config": {
                "age_group": "ragazzo",
                "activity_mode": "quiz",
                "language_target": "english",
                "learning_step": 1,
            },
        })

        with patch("core.state.save_json_direct"), patch("core.state.bus"):
            res = client.post("/api/rfid/trigger", json={"rfid_code": "EDU:AA:BB:CC"})

        assert res.status_code == 200
        data = res.get_json()
        assert data["mode"] == "edu_ai"
        assert ai_settings["age_group"] == "ragazzo"
        assert ai_settings["activity_mode"] == "quiz"
