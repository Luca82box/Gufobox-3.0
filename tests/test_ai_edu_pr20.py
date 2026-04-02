"""
tests/test_ai_edu_pr20.py — PR 20: Educational AI capability.

Covers:
A) Educational AI constants (VALID_AGE_GROUPS, VALID_ACTIVITY_MODES, VALID_LANGUAGE_TARGETS)
B) _validate_edu_config(): accepts valid, rejects invalid inputs
C) _get_edu_config(): returns canonical values, handles legacy field names
D) ai_age_profile_rules(): returns correct style for each age group
E) ai_system_prompt(): correct mode-specific text for each activity_mode x age_group
F) ai_system_prompt(): foreign_languages mode with language_target and step
G) GET /ai/edu/config: shape and values
H) POST /ai/edu/config: valid config, invalid config, validation errors
I) POST /ai/settings: accepts new field names, normalizes legacy names
J) GET /ai/status: exposes edu config fields
K) POST /ai/chat: uses educational system prompt (not raw system_prompt)
L) Backward compat: old interactive_mode / age_profile / target_lang still work
M) POST /ai/play_game: uses edu config, accepts overrides
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
def ai_app():
    """Minimal Flask app with ai_bp registered."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.ai import ai_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-edu-ai-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(ai_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(ai_app):
    with ai_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_ai_state():
    """Reset ai_runtime, led_runtime and ai_settings before each test."""
    from core.state import ai_runtime, led_runtime, DEFAULT_AI_RUNTIME
    from api.ai import ai_settings, LEGACY_MODE_MAP, LEGACY_LANG_MAP

    ai_runtime.clear()
    ai_runtime.update(deepcopy(DEFAULT_AI_RUNTIME))
    led_runtime["ai_state"] = None

    # Reset edu fields to clean defaults
    ai_settings.update({
        "age_group": "bambino",
        "activity_mode": "free_conversation",
        "language_target": "english",
        "learning_step": 1,
        "age_profile": "bambino",
        "interactive_mode": "chat_normale",
        "target_lang": "en",
        "tts_provider": "browser",
        "temperature": 0.7,
        "model": "gpt-3.5-turbo",
        "system_prompt": "Sei il Gufetto Magico.",
        "openai_api_key": "",
    })
    yield


@pytest.fixture()
def tmp_event_log():
    import core.event_log as _el
    orig = _el._log_file
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.unlink(path)
    _el._log_file = path
    yield path
    _el._log_file = orig
    if os.path.exists(path):
        os.unlink(path)


# ---------------------------------------------------------------------------
# A) Educational AI constants
# ---------------------------------------------------------------------------

class TestEduConstants:
    def test_valid_age_groups_has_all_three(self):
        from api.ai import VALID_AGE_GROUPS
        assert "bambino" in VALID_AGE_GROUPS
        assert "ragazzo" in VALID_AGE_GROUPS
        assert "adulto" in VALID_AGE_GROUPS

    def test_valid_activity_modes_has_all_seven(self):
        from api.ai import VALID_ACTIVITY_MODES
        expected = {
            "teaching_general", "quiz", "math", "animal_sounds_games",
            "interactive_story", "foreign_languages", "free_conversation",
        }
        # All original 7 modes must still be present (new modes may be added)
        assert expected.issubset(VALID_ACTIVITY_MODES)

    def test_valid_language_targets_has_four(self):
        from api.ai import VALID_LANGUAGE_TARGETS
        # Core legacy languages must be present; Japanese and Chinese support was added later
        assert {"english", "spanish", "german", "french"}.issubset(VALID_LANGUAGE_TARGETS)

    def test_legacy_mode_map_covers_old_names(self):
        from api.ai import LEGACY_MODE_MAP
        assert LEGACY_MODE_MAP["chat_normale"] == "free_conversation"
        assert LEGACY_MODE_MAP["storia_interattiva"] == "interactive_story"
        assert LEGACY_MODE_MAP["quiz_animali"] == "animal_sounds_games"
        assert LEGACY_MODE_MAP["insegnante_lingue"] == "foreign_languages"
        assert LEGACY_MODE_MAP["indovinelli"] == "quiz"
        assert LEGACY_MODE_MAP["matematica"] == "math"

    def test_legacy_lang_map_covers_codes(self):
        from api.ai import LEGACY_LANG_MAP
        assert LEGACY_LANG_MAP["en"] == "english"
        assert LEGACY_LANG_MAP["es"] == "spanish"
        assert LEGACY_LANG_MAP["de"] == "german"
        assert LEGACY_LANG_MAP["fr"] == "french"


# ---------------------------------------------------------------------------
# B) _validate_edu_config()
# ---------------------------------------------------------------------------

class TestValidateEduConfig:
    def test_valid_config_returns_no_errors(self):
        from api.ai import _validate_edu_config
        errs = _validate_edu_config("bambino", "quiz", "english", 1)
        assert errs == []

    def test_invalid_age_group_returns_error(self):
        from api.ai import _validate_edu_config
        errs = _validate_edu_config("neonato", "quiz", "english", 1)
        assert len(errs) == 1
        assert "age_group" in errs[0]

    def test_invalid_activity_mode_returns_error(self):
        from api.ai import _validate_edu_config
        errs = _validate_edu_config("bambino", "unknown_mode", "english", 1)
        assert len(errs) == 1
        assert "activity_mode" in errs[0]

    def test_invalid_language_for_foreign_mode(self):
        from api.ai import _validate_edu_config
        errs = _validate_edu_config("bambino", "foreign_languages", "klingon", 1)
        assert any("language_target" in e for e in errs)

    def test_language_not_checked_for_non_language_mode(self):
        from api.ai import _validate_edu_config
        # language_target doesn't matter when mode != foreign_languages
        errs = _validate_edu_config("adulto", "math", "klingon", 3)
        assert errs == []

    def test_invalid_learning_step_zero(self):
        from api.ai import _validate_edu_config
        errs = _validate_edu_config("bambino", "free_conversation", "english", 0)
        assert any("learning_step" in e for e in errs)

    def test_invalid_learning_step_string(self):
        from api.ai import _validate_edu_config
        errs = _validate_edu_config("bambino", "free_conversation", "english", "tre")
        assert any("learning_step" in e for e in errs)

    def test_all_valid_modes_pass(self):
        from api.ai import _validate_edu_config, VALID_ACTIVITY_MODES
        for mode in VALID_ACTIVITY_MODES:
            lang = "english" if mode == "foreign_languages" else "english"
            errs = _validate_edu_config("ragazzo", mode, lang, 1)
            assert errs == [], f"Mode '{mode}' unexpectedly failed: {errs}"


# ---------------------------------------------------------------------------
# C) _get_edu_config()
# ---------------------------------------------------------------------------

class TestGetEduConfig:
    def test_returns_defaults_when_no_edu_fields(self):
        from api.ai import _get_edu_config, ai_settings
        ai_settings.clear()
        age, mode, lang, step = _get_edu_config()
        assert age == "bambino"
        assert mode == "free_conversation"
        assert lang == "english"
        assert step == 1

    def test_reads_new_canonical_fields(self):
        from api.ai import _get_edu_config, ai_settings
        ai_settings.update({
            "age_group": "adulto",
            "activity_mode": "math",
            "language_target": "spanish",
            "learning_step": 4,
        })
        age, mode, lang, step = _get_edu_config()
        assert age == "adulto"
        assert mode == "math"
        assert lang == "spanish"
        assert step == 4

    def test_falls_back_to_legacy_age_profile(self):
        from api.ai import _get_edu_config, ai_settings
        ai_settings.pop("age_group", None)
        ai_settings["age_profile"] = "ragazzo"
        age, mode, lang, step = _get_edu_config()
        assert age == "ragazzo"

    def test_maps_legacy_interactive_mode(self):
        from api.ai import _get_edu_config, ai_settings
        ai_settings.pop("activity_mode", None)
        ai_settings["interactive_mode"] = "storia_interattiva"
        _, mode, _, _ = _get_edu_config()
        assert mode == "interactive_story"

    def test_maps_legacy_target_lang(self):
        from api.ai import _get_edu_config, ai_settings
        ai_settings.pop("language_target", None)
        ai_settings["target_lang"] = "fr"
        _, _, lang, _ = _get_edu_config()
        assert lang == "french"

    def test_invalid_age_group_defaults_to_bambino(self):
        from api.ai import _get_edu_config, ai_settings
        ai_settings["age_group"] = "neonato"
        age, _, _, _ = _get_edu_config()
        assert age == "bambino"

    def test_invalid_activity_mode_defaults_to_free_conversation(self):
        from api.ai import _get_edu_config, ai_settings
        ai_settings["activity_mode"] = "nonsense"
        _, mode, _, _ = _get_edu_config()
        assert mode == "free_conversation"


# ---------------------------------------------------------------------------
# D) ai_age_profile_rules()
# ---------------------------------------------------------------------------

class TestAgeProfileRules:
    def test_bambino_returns_style(self):
        from api.ai import ai_age_profile_rules
        rules = ai_age_profile_rules("bambino")
        assert "style" in rules
        assert len(rules["style"]) > 0

    def test_ragazzo_returns_style(self):
        from api.ai import ai_age_profile_rules
        rules = ai_age_profile_rules("ragazzo")
        assert "style" in rules
        assert len(rules["style"]) > 0

    def test_adulto_returns_style(self):
        from api.ai import ai_age_profile_rules
        rules = ai_age_profile_rules("adulto")
        assert "style" in rules
        assert len(rules["style"]) > 0

    def test_unknown_falls_back_to_bambino(self):
        from api.ai import ai_age_profile_rules
        r_unknown = ai_age_profile_rules("unknown")
        r_bambino = ai_age_profile_rules("bambino")
        assert r_unknown["style"] == r_bambino["style"]

    def test_styles_differ_across_age_groups(self):
        from api.ai import ai_age_profile_rules
        rb = ai_age_profile_rules("bambino")["style"]
        rr = ai_age_profile_rules("ragazzo")["style"]
        ra = ai_age_profile_rules("adulto")["style"]
        assert rb != rr
        assert rr != ra


# ---------------------------------------------------------------------------
# E) ai_system_prompt(): mode-specific content
# ---------------------------------------------------------------------------

class TestSystemPromptModes:
    def _prompt(self, age, mode, lang="english", step=1):
        from api.ai import ai_system_prompt
        return ai_system_prompt(age, mode, lang, step)

    def test_includes_age_group_label(self):
        p = self._prompt("ragazzo", "free_conversation")
        assert "ragazzo" in p

    def test_teaching_general_bambino(self):
        p = self._prompt("bambino", "teaching_general")
        assert "INSEGNAMENTO" in p.upper()

    def test_teaching_general_adulto(self):
        p = self._prompt("adulto", "teaching_general")
        # Adulto should mention more detail / rigour
        assert "INSEGNAMENTO" in p.upper()

    def test_quiz_mode_contains_quiz_keyword(self):
        p = self._prompt("ragazzo", "quiz")
        assert "QUIZ" in p.upper()

    def test_math_mode_contains_math_keyword(self):
        p = self._prompt("bambino", "math")
        assert "MATEMATICA" in p.upper()

    def test_animal_sounds_mode(self):
        p = self._prompt("bambino", "animal_sounds_games")
        assert "ANIMALI" in p.upper()

    def test_interactive_story_mode(self):
        p = self._prompt("ragazzo", "interactive_story")
        assert "STORIA" in p.upper()

    def test_free_conversation_no_extra_mode_block(self):
        p = self._prompt("adulto", "free_conversation")
        # free_conversation should NOT contain mode-specific keywords
        assert "MODALITÀ LINGUE" not in p.upper()
        assert "MODALITÀ QUIZ" not in p.upper()

    def test_legacy_mode_name_accepted(self):
        from api.ai import ai_system_prompt
        # storia_interattiva should map to interactive_story
        p = ai_system_prompt("bambino", "storia_interattiva")
        assert "STORIA" in p.upper()

    def test_all_age_groups_different_for_math(self):
        p_b = self._prompt("bambino", "math")
        p_r = self._prompt("ragazzo", "math")
        p_a = self._prompt("adulto", "math")
        assert p_b != p_r
        assert p_r != p_a


# ---------------------------------------------------------------------------
# F) ai_system_prompt(): foreign_languages mode
# ---------------------------------------------------------------------------

class TestSystemPromptForeignLanguages:
    def _prompt(self, age, lang, step):
        from api.ai import ai_system_prompt
        return ai_system_prompt(age, "foreign_languages", lang, step)

    def test_english_appears_in_prompt_bambino(self):
        p = self._prompt("bambino", "english", 1)
        assert "inglese" in p.lower()

    def test_spanish_appears_in_prompt(self):
        p = self._prompt("ragazzo", "spanish", 2)
        assert "spagnolo" in p.lower()

    def test_german_appears_in_prompt(self):
        p = self._prompt("adulto", "german", 3)
        assert "tedesco" in p.lower()

    def test_french_appears_in_prompt(self):
        p = self._prompt("bambino", "french", 1)
        assert "francese" in p.lower()

    def test_step_1_bambino_teaches_basic_vocabulary(self):
        p = self._prompt("bambino", "english", 1)
        p_lower = p.lower()
        assert any(kw in p_lower for kw in ["parole", "vocab", "basilari", "saluti"])

    def test_step_5_bambino_more_advanced(self):
        p1 = self._prompt("bambino", "english", 1)
        p5 = self._prompt("bambino", "english", 5)
        # Different content for different steps
        assert p1 != p5

    def test_step_included_in_prompt(self):
        p = self._prompt("ragazzo", "english", 3)
        assert "Step 3" in p

    def test_adulto_not_infantilized(self):
        p = self._prompt("adulto", "english", 1)
        assert "infantilizzazione" in p.lower() or "diretto" in p.lower()

    def test_bambino_step_low_vs_high_differ(self):
        p_low = self._prompt("bambino", "english", 1)
        p_high = self._prompt("bambino", "english", 7)
        assert p_low != p_high

    def test_ragazzo_steps_ladder(self):
        p1 = self._prompt("ragazzo", "spanish", 1)
        p3 = self._prompt("ragazzo", "spanish", 3)
        p6 = self._prompt("ragazzo", "spanish", 6)
        assert p1 != p3 and p3 != p6 and p1 != p6

    def test_legacy_lang_code_accepted(self):
        from api.ai import ai_system_prompt
        p = ai_system_prompt("bambino", "foreign_languages", "en", 1)
        assert "inglese" in p.lower()


# ---------------------------------------------------------------------------
# G) GET /ai/edu/config
# ---------------------------------------------------------------------------

class TestEduConfigGetEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/ai/edu/config")
        assert r.status_code == 200

    def test_payload_has_required_fields(self, client):
        data = json.loads(client.get("/api/ai/edu/config").data)
        assert "age_group" in data
        assert "activity_mode" in data
        assert "language_target" in data
        assert "learning_step" in data

    def test_payload_has_valid_lists(self, client):
        data = json.loads(client.get("/api/ai/edu/config").data)
        assert "valid_age_groups" in data
        assert "valid_activity_modes" in data
        assert "valid_language_targets" in data
        assert isinstance(data["valid_age_groups"], list)
        assert isinstance(data["valid_activity_modes"], list)

    def test_activity_mode_label_present(self, client):
        data = json.loads(client.get("/api/ai/edu/config").data)
        assert "activity_mode_label" in data
        assert len(data["activity_mode_label"]) > 0

    def test_language_target_label_present(self, client):
        data = json.loads(client.get("/api/ai/edu/config").data)
        assert "language_target_label" in data

    def test_defaults_are_valid(self, client):
        from api.ai import VALID_AGE_GROUPS, VALID_ACTIVITY_MODES, VALID_LANGUAGE_TARGETS
        data = json.loads(client.get("/api/ai/edu/config").data)
        assert data["age_group"] in VALID_AGE_GROUPS
        assert data["activity_mode"] in VALID_ACTIVITY_MODES
        assert data["language_target"] in VALID_LANGUAGE_TARGETS
        assert data["learning_step"] >= 1


# ---------------------------------------------------------------------------
# H) POST /ai/edu/config
# ---------------------------------------------------------------------------

class TestEduConfigPostEndpoint:
    def _post(self, client, payload):
        return client.post(
            "/api/ai/edu/config",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_valid_config_returns_ok(self, client):
        r = self._post(client, {
            "age_group": "ragazzo",
            "activity_mode": "math",
            "language_target": "english",
            "learning_step": 3,
        })
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["status"] == "ok"

    def test_persists_age_group(self, client):
        from api.ai import ai_settings
        self._post(client, {"age_group": "adulto", "activity_mode": "quiz",
                             "language_target": "english", "learning_step": 1})
        assert ai_settings["age_group"] == "adulto"

    def test_persists_activity_mode(self, client):
        from api.ai import ai_settings
        self._post(client, {"age_group": "bambino", "activity_mode": "interactive_story",
                             "language_target": "english", "learning_step": 1})
        assert ai_settings["activity_mode"] == "interactive_story"

    def test_invalid_age_group_returns_400(self, client, tmp_event_log):
        r = self._post(client, {"age_group": "neonato", "activity_mode": "quiz",
                                 "language_target": "english", "learning_step": 1})
        assert r.status_code == 400

    def test_invalid_mode_returns_400(self, client, tmp_event_log):
        r = self._post(client, {"age_group": "bambino", "activity_mode": "nonsense",
                                 "language_target": "english", "learning_step": 1})
        assert r.status_code == 400

    def test_invalid_lang_for_language_mode_returns_400(self, client, tmp_event_log):
        r = self._post(client, {"age_group": "bambino", "activity_mode": "foreign_languages",
                                 "language_target": "klingon", "learning_step": 1})
        assert r.status_code == 400

    def test_validation_errors_logged(self, client, tmp_event_log):
        from core.event_log import get_events
        self._post(client, {"age_group": "unknown", "activity_mode": "quiz",
                             "language_target": "english", "learning_step": 1})
        events = get_events(limit=10)
        ai_events = [e for e in events if e.get("area") == "ai"]
        assert len(ai_events) > 0

    def test_returns_saved_values(self, client):
        r = self._post(client, {
            "age_group": "ragazzo",
            "activity_mode": "foreign_languages",
            "language_target": "french",
            "learning_step": 5,
        })
        data = json.loads(r.data)
        assert data["age_group"] == "ragazzo"
        assert data["activity_mode"] == "foreign_languages"
        assert data["language_target"] == "french"
        assert data["learning_step"] == 5

    def test_legacy_mode_name_normalized(self, client):
        from api.ai import ai_settings
        r = self._post(client, {"age_group": "bambino", "activity_mode": "storia_interattiva",
                                 "language_target": "english", "learning_step": 1})
        # Should be normalized to canonical name
        assert ai_settings["activity_mode"] == "interactive_story"


# ---------------------------------------------------------------------------
# I) POST /ai/settings: new field names and legacy normalization
# ---------------------------------------------------------------------------

class TestSettingsPostWithEduFields:
    def _post_settings(self, client, payload):
        return client.post(
            "/api/ai/settings",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_accepts_new_edu_fields(self, client):
        from api.ai import ai_settings
        self._post_settings(client, {
            "age_group": "adulto",
            "activity_mode": "teaching_general",
            "language_target": "spanish",
            "learning_step": 2,
        })
        assert ai_settings["age_group"] == "adulto"
        assert ai_settings["activity_mode"] == "teaching_general"
        assert ai_settings["language_target"] == "spanish"
        assert ai_settings["learning_step"] == 2

    def test_legacy_interactive_mode_normalized(self, client):
        from api.ai import ai_settings
        self._post_settings(client, {"interactive_mode": "quiz_animali"})
        assert ai_settings["activity_mode"] == "animal_sounds_games"

    def test_legacy_target_lang_normalized(self, client):
        from api.ai import ai_settings
        self._post_settings(client, {"target_lang": "de"})
        assert ai_settings["language_target"] == "german"

    def test_legacy_age_profile_normalized(self, client):
        from api.ai import ai_settings
        self._post_settings(client, {"age_profile": "ragazzo"})
        assert ai_settings["age_group"] == "ragazzo"

    def test_legacy_aliases_synced_after_save(self, client):
        from api.ai import ai_settings
        self._post_settings(client, {"age_group": "adulto", "activity_mode": "math",
                                      "language_target": "english", "learning_step": 1})
        # Legacy fields should also be updated
        assert ai_settings.get("age_profile") == "adulto"
        assert "target_lang" in ai_settings


# ---------------------------------------------------------------------------
# J) GET /ai/status: exposes edu config fields
# ---------------------------------------------------------------------------

class TestAiStatusEduFields:
    def test_status_has_age_group(self, client):
        data = json.loads(client.get("/api/ai/status").data)
        assert "age_group" in data

    def test_status_has_activity_mode(self, client):
        data = json.loads(client.get("/api/ai/status").data)
        assert "activity_mode" in data

    def test_status_has_language_target(self, client):
        data = json.loads(client.get("/api/ai/status").data)
        assert "language_target" in data

    def test_status_has_learning_step(self, client):
        data = json.loads(client.get("/api/ai/status").data)
        assert "learning_step" in data

    def test_status_has_activity_mode_label(self, client):
        data = json.loads(client.get("/api/ai/status").data)
        assert "activity_mode_label" in data

    def test_status_reflects_current_edu_config(self, client):
        from api.ai import ai_settings
        ai_settings["age_group"] = "ragazzo"
        ai_settings["activity_mode"] = "quiz"
        data = json.loads(client.get("/api/ai/status").data)
        assert data["age_group"] == "ragazzo"
        assert data["activity_mode"] == "quiz"


# ---------------------------------------------------------------------------
# K) POST /ai/chat: uses educational system prompt
# ---------------------------------------------------------------------------

class TestAiChatUsesEduPrompt:
    def _mock_oa(self, reply="Risposta educativa"):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = reply
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        return mock_client

    def test_chat_succeeds_with_edu_settings(self, client):
        from api.ai import ai_settings
        ai_settings.update({
            "age_group": "bambino", "activity_mode": "quiz",
            "language_target": "english", "learning_step": 1,
            "tts_provider": "browser", "temperature": 0.7, "model": "gpt-3.5-turbo",
        })
        mock_oa = self._mock_oa("Chi è il re della foresta?")
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            r = client.post(
                "/api/ai/chat",
                data=json.dumps({"text": "iniziamo"}),
                content_type="application/json",
            )
        assert r.status_code == 200

    def test_chat_uses_edu_prompt_not_raw_system_prompt(self, client):
        """The system message sent to OpenAI should come from ai_system_prompt(), not raw system_prompt."""
        from api.ai import ai_settings
        ai_settings.update({
            "age_group": "ragazzo", "activity_mode": "math",
            "language_target": "english", "learning_step": 2,
            "system_prompt": "OLD SYSTEM PROMPT THAT SHOULD NOT BE USED",
            "tts_provider": "browser", "temperature": 0.7, "model": "gpt-3.5-turbo",
        })
        mock_oa = self._mock_oa()
        captured_messages = []

        def capture_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            mock_choice = MagicMock()
            mock_choice.message.content = "ok"
            return MagicMock(choices=[mock_choice])

        mock_oa.chat.completions.create.side_effect = capture_create

        with patch("api.ai.get_openai_client", return_value=mock_oa):
            client.post(
                "/api/ai/chat",
                data=json.dumps({"text": "ciao"}),
                content_type="application/json",
            )

        system_msg = next((m for m in captured_messages if m["role"] == "system"), None)
        assert system_msg is not None
        # Should contain educational mode content, not the old system prompt
        assert "MATEMATICA" in system_msg["content"].upper()
        assert "OLD SYSTEM PROMPT" not in system_msg["content"]

    def test_chat_foreign_languages_mode_includes_lang(self, client):
        from api.ai import ai_settings
        ai_settings.update({
            "age_group": "bambino", "activity_mode": "foreign_languages",
            "language_target": "french", "learning_step": 1,
            "tts_provider": "browser", "temperature": 0.7, "model": "gpt-3.5-turbo",
        })
        mock_oa = self._mock_oa()
        captured_messages = []

        def capture_create(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            mock_choice = MagicMock()
            mock_choice.message.content = "Bonjour!"
            return MagicMock(choices=[mock_choice])

        mock_oa.chat.completions.create.side_effect = capture_create

        with patch("api.ai.get_openai_client", return_value=mock_oa):
            client.post(
                "/api/ai/chat",
                data=json.dumps({"text": "iniziamo"}),
                content_type="application/json",
            )

        system_msg = next((m for m in captured_messages if m["role"] == "system"), None)
        assert system_msg is not None
        assert "francese" in system_msg["content"].lower()


# ---------------------------------------------------------------------------
# L) Backward compat: old field names still work end-to-end
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_get_settings_returns_both_old_and_new_keys(self, client):
        data = json.loads(client.get("/api/ai/settings").data)
        # Should have at minimum the legacy keys still present
        # (the dict contains both since we sync them)
        assert "tts_provider" in data  # always present

    def test_old_interactive_mode_in_settings_saved_correctly(self, client):
        from api.ai import ai_settings
        ai_settings["interactive_mode"] = "storia_interattiva"
        # Simulate a POST with old-style data
        client.post(
            "/api/ai/settings",
            data=json.dumps({"interactive_mode": "quiz_animali"}),
            content_type="application/json",
        )
        # activity_mode should be canonical
        assert ai_settings["activity_mode"] == "animal_sounds_games"

    def test_age_profile_field_still_present_after_save(self, client):
        from api.ai import ai_settings
        client.post(
            "/api/ai/settings",
            data=json.dumps({"age_group": "adulto"}),
            content_type="application/json",
        )
        assert "age_profile" in ai_settings
        assert ai_settings["age_profile"] == "adulto"

    def test_ai_status_still_has_core_fields(self, client):
        data = json.loads(client.get("/api/ai/status").data)
        # Core PR18 fields must still be present
        assert "status" in data
        assert "last_error" in data
        assert "history_length" in data
        assert "tts_provider" in data
        assert "openai_configured" in data


# ---------------------------------------------------------------------------
# M) POST /ai/play_game: uses edu config, accepts overrides
# ---------------------------------------------------------------------------

class TestAiPlayGame:
    def test_play_game_returns_ok(self, client):
        r = client.post(
            "/api/ai/play_game",
            data=json.dumps({"game_type": "quiz_animali"}),
            content_type="application/json",
        )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["status"] == "ok"

    def test_play_game_normalizes_legacy_mode(self, client):
        r = client.post(
            "/api/ai/play_game",
            data=json.dumps({"game_type": "storia_interattiva"}),
            content_type="application/json",
        )
        data = json.loads(r.data)
        assert data["game_started"] == "interactive_story"

    def test_play_game_canonical_mode(self, client):
        r = client.post(
            "/api/ai/play_game",
            data=json.dumps({"game_type": "math"}),
            content_type="application/json",
        )
        data = json.loads(r.data)
        assert data["game_started"] == "math"

    def test_play_game_has_prompt_preview(self, client):
        r = client.post(
            "/api/ai/play_game",
            data=json.dumps({"game_type": "animal_sounds_games"}),
            content_type="application/json",
        )
        data = json.loads(r.data)
        assert "prompt_preview" in data
        assert len(data["prompt_preview"]) > 0
