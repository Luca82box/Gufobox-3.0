"""
tests/test_wizard_admin_wiring_pr25.py — PR 25: Wizard runtime → admin config wiring.

Verifies that core/wizard.py reads activity options from the admin-configured
ai_settings["wizard_categories"] instead of the hardcoded CATEGORY_ACTIVITIES.

Covers:
1. wizard proposes activities configured via admin (school)
2. wizard proposes activities configured via admin (entertainment)
3. disabled activities are NOT proposed
4. order of activities matches admin config order
5. fallback to defaults when wizard_categories is absent
6. fallback to defaults when wizard_categories is corrupted/invalid
7. fallback to defaults when all activities are disabled
8. fallback to defaults when category entry is missing
9. school_conversation is available when enabled
10. foreign_languages still triggers language + step stages
11. RFID trigger school/entertainment starts wizard with configured activities
12. API: POST /wizard/start returns configured activities after admin POST
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
    flask_app.secret_key = "test-wiring-secret"
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


@pytest.fixture()
def tmp_files(tmp_path):
    """Redirect file-backed stores to temp files for isolation."""
    import api.rfid as _rfid_mod
    import api.ai as _ai_mod
    import core.event_log as _el

    rfid_f = str(tmp_path / "rfid_profiles.json")
    ai_f = str(tmp_path / "ai_settings.json")
    event_f = str(tmp_path / "events.jsonl")

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



@pytest.fixture(autouse=True)
def reset_state():
    """Reset ai_settings and wizard_state before each test."""
    from api.ai import ai_settings
    from core.wizard import wizard_state

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


@pytest.fixture(autouse=True)
def mock_openai_available():
    """Patch has_openai to return True so RFID trigger tests work without a real API key."""
    with patch("api.rfid.has_openai", return_value=True):
        yield


# ---------------------------------------------------------------------------
# 1–2. Wizard proposes activities configured via admin
# ---------------------------------------------------------------------------

class TestWizardUsesAdminConfiguredActivities:

    def test_school_uses_admin_activities(self):
        """Wizard proposes only the activities configured in admin for school."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, STAGE_ACTIVITY, STAGE_AGE

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "teaching_general", "label": "Insegnamento", "enabled": True},
                    {"id": "math", "label": "Matematica", "enabled": True},
                ],
            }
        }

        state = wizard_start("school", "RFID001")
        assert state["active"] is True
        assert state["current_stage"] == STAGE_AGE

        from core.wizard import wizard_submit
        state = wizard_submit("bambino")
        assert state["current_stage"] == STAGE_ACTIVITY
        assert state["current_options"] == ["teaching_general", "math"]

    def test_entertainment_uses_admin_activities(self):
        """Wizard proposes only the activities configured in admin for entertainment."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, STAGE_ACTIVITY

        ai_settings["wizard_categories"] = {
            "entertainment": {
                "label": "Intrattenimento",
                "activities": [
                    {"id": "quiz", "label": "Quiz", "enabled": True},
                    {"id": "interactive_story", "label": "Storia", "enabled": True},
                ],
            }
        }

        wizard_start("entertainment", "RFID002")
        state = wizard_submit("ragazzo")
        assert state["current_stage"] == STAGE_ACTIVITY
        assert state["current_options"] == ["quiz", "interactive_story"]


# ---------------------------------------------------------------------------
# 3. Disabled activities are NOT proposed
# ---------------------------------------------------------------------------

class TestDisabledActivitiesNotProposed:

    def test_disabled_activity_excluded(self):
        """An activity with enabled=False must not appear in wizard options."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "teaching_general", "label": "Ins.", "enabled": True},
                    {"id": "math", "label": "Mat.", "enabled": False},
                    {"id": "school_conversation", "label": "Conv.", "enabled": True},
                ],
            }
        }

        wizard_start("school")
        state = wizard_submit("bambino")
        assert "math" not in state["current_options"]
        assert "teaching_general" in state["current_options"]
        assert "school_conversation" in state["current_options"]

    def test_all_disabled_falls_back_to_default(self):
        """If all activities are disabled, fall back to default list."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "teaching_general", "label": "Ins.", "enabled": False},
                    {"id": "math", "label": "Mat.", "enabled": False},
                ],
            }
        }

        wizard_start("school")
        state = wizard_submit("bambino")
        # Must fall back to hardcoded defaults
        assert state["current_options"] == list(CATEGORY_ACTIVITIES["school"])


# ---------------------------------------------------------------------------
# 4. Order of activities matches admin config order
# ---------------------------------------------------------------------------

class TestActivityOrderPreserved:

    def test_order_matches_admin_config(self):
        """Activities are proposed in the order set by the admin."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit

        ordered = [
            {"id": "free_conversation", "label": "Free", "enabled": True},
            {"id": "quiz", "label": "Quiz", "enabled": True},
            {"id": "interactive_story", "label": "Story", "enabled": True},
        ]
        ai_settings["wizard_categories"] = {
            "entertainment": {
                "label": "Ent.",
                "activities": ordered,
            }
        }

        wizard_start("entertainment")
        state = wizard_submit("adulto")
        assert state["current_options"] == ["free_conversation", "quiz", "interactive_story"]


# ---------------------------------------------------------------------------
# 5–8. Fallback scenarios
# ---------------------------------------------------------------------------

class TestFallbackToDefaults:

    def test_fallback_when_wizard_categories_absent(self):
        """No wizard_categories in ai_settings → use hardcoded defaults."""
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES

        # ai_settings has no "wizard_categories" (ensured by fixture)
        wizard_start("school")
        state = wizard_submit("bambino")
        assert state["current_options"] == list(CATEGORY_ACTIVITIES["school"])

    def test_fallback_when_wizard_categories_is_not_dict(self):
        """wizard_categories = None → fallback."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES

        ai_settings["wizard_categories"] = None
        wizard_start("entertainment")
        state = wizard_submit("ragazzo")
        assert state["current_options"] == list(CATEGORY_ACTIVITIES["entertainment"])

    def test_fallback_when_wizard_categories_is_invalid_string(self):
        """wizard_categories = 'corrupted' → fallback."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES

        ai_settings["wizard_categories"] = "corrupted"
        wizard_start("school")
        state = wizard_submit("bambino")
        assert state["current_options"] == list(CATEGORY_ACTIVITIES["school"])

    def test_fallback_when_category_entry_missing(self):
        """wizard_categories exists but missing the requested category → fallback."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES

        ai_settings["wizard_categories"] = {
            "entertainment": {
                "label": "Ent.",
                "activities": [
                    {"id": "quiz", "label": "Quiz", "enabled": True},
                ],
            }
        }
        # school is missing from the config
        wizard_start("school")
        state = wizard_submit("bambino")
        assert state["current_options"] == list(CATEGORY_ACTIVITIES["school"])

    def test_fallback_when_activities_is_not_list(self):
        """activities field is not a list → fallback."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": "not-a-list",
            }
        }
        wizard_start("school")
        state = wizard_submit("bambino")
        assert state["current_options"] == list(CATEGORY_ACTIVITIES["school"])

    def test_fallback_when_all_activities_disabled_entertainment(self):
        """All entertainment activities disabled → fallback."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, CATEGORY_ACTIVITIES

        ai_settings["wizard_categories"] = {
            "entertainment": {
                "label": "Ent.",
                "activities": [
                    {"id": "quiz", "label": "Quiz", "enabled": False},
                    {"id": "free_conversation", "label": "Free", "enabled": False},
                ],
            }
        }
        wizard_start("entertainment")
        state = wizard_submit("adulto")
        assert state["current_options"] == list(CATEGORY_ACTIVITIES["entertainment"])


# ---------------------------------------------------------------------------
# 9. school_conversation available when enabled
# ---------------------------------------------------------------------------

class TestSchoolConversationAvailable:

    def test_school_conversation_shown_when_enabled(self):
        """school_conversation appears in wizard options when admin has it enabled."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "teaching_general", "label": "Ins.", "enabled": True},
                    {"id": "school_conversation", "label": "Conv.", "enabled": True},
                ],
            }
        }

        wizard_start("school")
        state = wizard_submit("ragazzo")
        assert "school_conversation" in state["current_options"]

    def test_school_conversation_not_shown_when_disabled(self):
        """school_conversation does NOT appear in wizard options when disabled."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "teaching_general", "label": "Ins.", "enabled": True},
                    {"id": "school_conversation", "label": "Conv.", "enabled": False},
                ],
            }
        }

        wizard_start("school")
        state = wizard_submit("ragazzo")
        assert "school_conversation" not in state["current_options"]


# ---------------------------------------------------------------------------
# 10. foreign_languages still triggers language + step stages
# ---------------------------------------------------------------------------

class TestForeignLanguagesStagesUnchanged:

    def test_foreign_languages_triggers_language_stage(self):
        """Selecting foreign_languages still leads to language_target stage."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, STAGE_LANGUAGE

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "foreign_languages", "label": "Lingue", "enabled": True},
                ],
            }
        }

        wizard_start("school")
        wizard_submit("bambino")        # age_group
        state = wizard_submit("foreign_languages")  # activity_mode
        assert state["current_stage"] == STAGE_LANGUAGE

    def test_foreign_languages_full_path(self):
        """foreign_languages path: age → activity → language → step → done."""
        from api.ai import ai_settings
        from core.wizard import wizard_start, wizard_submit, STAGE_DONE

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "foreign_languages", "label": "Lingue", "enabled": True},
                ],
            }
        }

        wizard_start("school")
        wizard_submit("adulto")               # age_group
        wizard_submit("foreign_languages")    # activity_mode
        wizard_submit("english")              # language_target
        state = wizard_submit("3")            # learning_step
        assert state["current_stage"] == STAGE_DONE
        assert state["completed_config"]["language_target"] == "english"
        assert state["completed_config"]["learning_step"] == 3


# ---------------------------------------------------------------------------
# 11. RFID trigger uses configured activities
# ---------------------------------------------------------------------------

class TestRfidTriggerUsesConfiguredActivities:

    def test_school_rfid_trigger_produces_configured_activities(self, client, tmp_files):
        """POST /rfid/trigger with school RFID starts wizard with admin-configured activities."""
        from api.ai import ai_settings

        ai_settings["wizard_categories"] = {
            "school": {
                "label": "Scuola",
                "activities": [
                    {"id": "math", "label": "Mat.", "enabled": True},
                    {"id": "school_conversation", "label": "Conv.", "enabled": True},
                ],
            }
        }
        # Create school RFID profile
        client.post("/api/rfid/profile", json={
            "rfid_code": "SCH:00:00:01",
            "name": "Scuola",
            "mode": "school",
        })

        with patch("api.rfid.bus"):
            resp = client.post("/api/rfid/trigger", json={"rfid_code": "SCH:00:00:01"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["wizard"]["active"] is True
        assert data["wizard"]["current_stage"] == "age_group"

        # Submit age to reach activity stage and verify configured options
        from core.wizard import wizard_submit
        state = wizard_submit("bambino")
        assert state["current_options"] == ["math", "school_conversation"]


# ---------------------------------------------------------------------------
# 12. API round-trip: POST categories then start wizard
# ---------------------------------------------------------------------------

class TestApiRoundTrip:

    def test_post_categories_then_wizard_uses_them(self, client):
        """Configure categories via API, then start wizard; options match."""
        # Update categories via admin API
        resp = client.post("/api/ai/wizard/categories", json={
            "entertainment": {
                "activities": [
                    {"id": "quiz", "label": "Quiz", "enabled": True},
                    {"id": "animal_sounds_games", "label": "Animali", "enabled": False},
                    {"id": "interactive_story", "label": "Storia", "enabled": True},
                ]
            }
        })
        assert resp.status_code == 200

        # Start wizard for entertainment
        resp2 = client.post("/api/wizard/start", json={"category": "entertainment"})
        assert resp2.status_code == 200

        # Submit age → reach activity stage
        resp3 = client.post("/api/wizard/submit", json={"answer": "bambino"})
        data3 = resp3.get_json()
        opts = data3.get("wizard", data3).get("current_options", [])
        # Disabled animal_sounds_games must be absent
        assert "animal_sounds_games" not in opts
        assert "quiz" in opts
        assert "interactive_story" in opts

    def test_post_categories_school_then_wizard_uses_them(self, client):
        """Configure school categories via API, then start wizard; options match."""
        resp = client.post("/api/ai/wizard/categories", json={
            "school": {
                "activities": [
                    {"id": "teaching_general", "label": "Ins.", "enabled": True},
                    {"id": "math", "label": "Mat.", "enabled": True},
                    {"id": "foreign_languages", "label": "Lingue", "enabled": False},
                    {"id": "school_conversation", "label": "Conv.", "enabled": True},
                ]
            }
        })
        assert resp.status_code == 200

        resp2 = client.post("/api/wizard/start", json={"category": "school"})
        assert resp2.status_code == 200

        resp3 = client.post("/api/wizard/submit", json={"answer": "adulto"})
        data3 = resp3.get_json()
        opts = data3.get("wizard", data3).get("current_options", [])
        assert "foreign_languages" not in opts
        assert "teaching_general" in opts
        assert "math" in opts
        assert "school_conversation" in opts
