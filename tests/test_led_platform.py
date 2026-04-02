"""
test_led_platform.py — PR 3: LED Platform

Testa:
 - validate_led_assignment()
 - validate_custom_led_effect() (inclusi tipi sequence/random_mix/scene)
 - gerarchia sorgenti: AI > master > RFID > default
 - CRUD effetti custom a livello logico
 - smoke tests endpoint LED principali
 - integrazione AI state → LED runtime
 - integrazione RFID trigger → LED runtime
"""
import os
import json
import copy
import tempfile
import pytest


# ---------------------------------------------------------------------------
# Helper: patch LED_EFFECTS_CUSTOM_DIR su un tmpdir per i test
# ---------------------------------------------------------------------------
import api.led as led_module


def _tmp_custom_dir(tmpdir):
    orig = led_module.LED_EFFECTS_CUSTOM_DIR
    led_module.LED_EFFECTS_CUSTOM_DIR = tmpdir
    return orig


# ===========================================================================
# A) validate_led_assignment
# ===========================================================================

class TestValidateLedAssignment:

    def test_valid_full_assignment(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment({
            "effect_id": "breathing",
            "color": "#44ddff",
            "brightness": 55,
            "speed": 20,
            "params": {},
        })
        assert ok is True
        assert err is None

    def test_missing_effect_id(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment({"color": "#ff0000", "brightness": 50, "speed": 30, "params": {}})
        assert ok is False
        assert "effect_id" in err.lower()

    def test_invalid_color_format(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment({"effect_id": "solid", "color": "red", "brightness": 50, "speed": 30, "params": {}})
        assert ok is False
        assert "colore" in err.lower() or "color" in err.lower()

    def test_brightness_out_of_range(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment({"effect_id": "solid", "color": "#ff0000", "brightness": 150, "speed": 30, "params": {}})
        assert ok is False
        assert "brightness" in err.lower()

    def test_speed_out_of_range_negative(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment({"effect_id": "solid", "color": "#ff0000", "brightness": 50, "speed": -5, "params": {}})
        assert ok is False
        assert "speed" in err.lower()

    def test_params_not_dict(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment({"effect_id": "solid", "color": "#ff0000", "brightness": 50, "speed": 30, "params": "wrong"})
        assert ok is False
        assert "params" in err.lower()

    def test_not_dict_rejected(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment("not a dict")
        assert ok is False

    def test_effect_id_with_invalid_chars(self):
        from api.led import validate_led_assignment
        ok, err = validate_led_assignment({"effect_id": "../../etc/passwd", "color": "#ff0000", "brightness": 50, "speed": 30, "params": {}})
        assert ok is False

    def test_valid_black_color(self):
        from api.led import validate_led_assignment
        ok, _ = validate_led_assignment({"effect_id": "off", "color": "#000000", "brightness": 0, "speed": 0, "params": {}})
        assert ok is True

    def test_valid_max_values(self):
        from api.led import validate_led_assignment
        ok, _ = validate_led_assignment({"effect_id": "rainbow", "color": "#ffffff", "brightness": 100, "speed": 100, "params": {}})
        assert ok is True


# ===========================================================================
# B) validate_custom_led_effect
# ===========================================================================

class TestValidateCustomLedEffect:

    def test_valid_basic_effect(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "my_effect", "name": "My Effect"})
        assert ok is True
        assert err is None

    def test_missing_name(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "my_effect"})
        assert ok is False

    def test_builtin_id_rejected(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "rainbow", "name": "Custom Rainbow"})
        assert ok is False
        assert "builtin" in (err or "").lower()

    def test_invalid_effect_id_chars(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "../etc/evil", "name": "Evil"})
        assert ok is False

    def test_sequence_type_requires_steps(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "my_seq", "name": "Seq", "type": "sequence"})
        assert ok is False
        assert "steps" in (err or "").lower()

    def test_sequence_type_valid_with_steps(self):
        from api.led import validate_custom_led_effect
        ok, _ = validate_custom_led_effect({
            "id": "my_seq",
            "name": "Seq",
            "type": "sequence",
            "steps": [{"effect_id": "solid", "duration_ms": 500}],
        })
        assert ok is True

    def test_random_mix_requires_pool(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "my_mix", "name": "Mix", "type": "random_mix"})
        assert ok is False
        assert "pool" in (err or "").lower()

    def test_random_mix_valid(self):
        from api.led import validate_custom_led_effect
        ok, _ = validate_custom_led_effect({
            "id": "my_mix",
            "name": "Mix",
            "type": "random_mix",
            "pool": ["solid", "breathing"],
        })
        assert ok is True

    def test_scene_type_requires_slots(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "my_scene", "name": "Scene", "type": "scene"})
        assert ok is False
        assert "slots" in (err or "").lower()

    def test_params_must_be_dict_if_present(self):
        from api.led import validate_custom_led_effect
        ok, err = validate_custom_led_effect({"id": "my_eff", "name": "E", "params": "bad"})
        assert ok is False

    def test_non_dict_rejected(self):
        from api.led import validate_custom_led_effect
        ok, _ = validate_custom_led_effect([1, 2, 3])
        assert ok is False


# ===========================================================================
# C) DEFAULT_LED_RUNTIME — nuovi campi presenti
# ===========================================================================

class TestDefaultLedRuntime:

    def test_new_fields_in_default_runtime(self):
        from core.state import DEFAULT_LED_RUNTIME
        assert "master_override_active" in DEFAULT_LED_RUNTIME
        assert "current_source" in DEFAULT_LED_RUNTIME
        assert "current_rfid" in DEFAULT_LED_RUNTIME
        assert "applied" in DEFAULT_LED_RUNTIME
        assert "last_updated_ts" in DEFAULT_LED_RUNTIME
        assert "ai_state" in DEFAULT_LED_RUNTIME

    def test_applied_has_required_keys(self):
        from core.state import DEFAULT_LED_RUNTIME
        applied = DEFAULT_LED_RUNTIME["applied"]
        for key in ("enabled", "effect_id", "color", "brightness", "speed", "params"):
            assert key in applied

    def test_legacy_fields_still_present(self):
        from core.state import DEFAULT_LED_RUNTIME
        for key in ("master_enabled", "current_effect", "master_color",
                    "master_brightness", "master_speed"):
            assert key in DEFAULT_LED_RUNTIME


# ===========================================================================
# D) DEFAULT_LED_MASTER — nuova struttura con settings sub-dict
# ===========================================================================

class TestDefaultLedMaster:

    def test_new_master_structure(self):
        from api.led import DEFAULT_LED_MASTER
        assert "settings" in DEFAULT_LED_MASTER
        assert "override_active" in DEFAULT_LED_MASTER
        assert "enabled" in DEFAULT_LED_MASTER

    def test_settings_has_required_keys(self):
        from api.led import DEFAULT_LED_MASTER
        settings = DEFAULT_LED_MASTER["settings"]
        for key in ("effect_id", "color", "brightness", "speed", "params"):
            assert key in settings

    def test_override_active_default_false(self):
        from api.led import DEFAULT_LED_MASTER
        assert DEFAULT_LED_MASTER["override_active"] is False


# ===========================================================================
# E) AI_LED_MAP
# ===========================================================================

class TestAiLedMap:

    def test_all_states_present(self):
        from api.led import AI_LED_MAP
        for state in ("idle", "listening", "thinking", "speaking", "error"):
            assert state in AI_LED_MAP

    def test_each_state_has_assignment_keys(self):
        from api.led import AI_LED_MAP
        for state, assignment in AI_LED_MAP.items():
            for key in ("enabled", "effect_id", "color", "brightness", "speed", "params"):
                assert key in assignment, f"Stato '{state}' manca il campo '{key}'"

    def test_each_state_has_valid_assignment(self):
        from api.led import AI_LED_MAP, validate_led_assignment
        for state, assignment in AI_LED_MAP.items():
            ok, err = validate_led_assignment(assignment)
            assert ok is True, f"Stato AI '{state}' ha assignment invalido: {err}"


# ===========================================================================
# F) Gerarchia sorgenti LED: AI > master > RFID > default
# ===========================================================================

class TestLedHierarchy:

    def setup_method(self):
        """Reset led_runtime before each test."""
        from core.state import led_runtime, DEFAULT_LED_RUNTIME
        led_runtime.clear()
        led_runtime.update(copy.deepcopy(DEFAULT_LED_RUNTIME))

    def _reset_master_file(self, tmpdir):
        orig = led_module.LED_MASTER_FILE
        led_module.LED_MASTER_FILE = os.path.join(tmpdir, "led_master_test.json")
        return orig

    def test_default_source_when_nothing_active(self):
        from api.led import get_effective_led_assignment, DEFAULT_LED_ASSIGNMENT
        from core.state import led_runtime
        led_runtime["ai_state"] = None
        led_runtime["current_rfid"] = None
        assignment, source = get_effective_led_assignment()
        assert source == "default"
        assert assignment["effect_id"] == DEFAULT_LED_ASSIGNMENT["effect_id"]

    def test_master_override_takes_priority_over_default(self):
        from api.led import get_effective_led_assignment
        from core.state import led_runtime
        import api.led as lm
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_master = lm.LED_MASTER_FILE
            lm.LED_MASTER_FILE = os.path.join(tmpdir, "master.json")
            # Write a master with override_active=True
            master_data = {
                "enabled": True,
                "override_active": True,
                "settings": {
                    "enabled": True,
                    "effect_id": "rainbow",
                    "color": "#ff9900",
                    "brightness": 80,
                    "speed": 40,
                    "params": {},
                },
            }
            with open(lm.LED_MASTER_FILE, "w") as f:
                json.dump(master_data, f)
            led_runtime["ai_state"] = None
            led_runtime["current_rfid"] = None
            assignment, source = get_effective_led_assignment()
            lm.LED_MASTER_FILE = orig_master
        assert source == "master"
        assert assignment["effect_id"] == "rainbow"

    def test_ai_state_overrides_master(self):
        from api.led import get_effective_led_assignment, AI_LED_MAP
        from core.state import led_runtime
        import api.led as lm
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_master = lm.LED_MASTER_FILE
            lm.LED_MASTER_FILE = os.path.join(tmpdir, "master.json")
            # Write master with override
            master_data = {
                "enabled": True,
                "override_active": True,
                "settings": {
                    "enabled": True, "effect_id": "solid",
                    "color": "#00ff00", "brightness": 80, "speed": 30, "params": {},
                },
            }
            with open(lm.LED_MASTER_FILE, "w") as f:
                json.dump(master_data, f)
            led_runtime["ai_state"] = "listening"
            led_runtime["current_rfid"] = None
            assignment, source = get_effective_led_assignment()
            lm.LED_MASTER_FILE = orig_master
        assert source == "ai"
        assert assignment["effect_id"] == AI_LED_MAP["listening"]["effect_id"]

    def test_rfid_profile_led_used_when_no_override(self):
        from api.led import get_effective_led_assignment
        from core.state import led_runtime, rfid_map
        import api.led as lm
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_master = lm.LED_MASTER_FILE
            lm.LED_MASTER_FILE = os.path.join(tmpdir, "master.json")
            # Master NOT active
            master_data = {
                "enabled": True, "override_active": False,
                "settings": {"effect_id": "solid", "color": "#0000ff",
                             "brightness": 70, "speed": 30, "params": {}},
            }
            with open(lm.LED_MASTER_FILE, "w") as f:
                json.dump(master_data, f)
            # Set active RFID with LED block
            rfid_map["TEST_UID"] = {
                "type": "audio",
                "target": "/test.mp3",
                "led": {
                    "enabled": True,
                    "effect_id": "breathing",
                    "color": "#44ddff",
                    "brightness": 60,
                    "speed": 25,
                    "params": {},
                },
            }
            led_runtime["ai_state"] = None
            led_runtime["current_rfid"] = "TEST_UID"
            assignment, source = get_effective_led_assignment()
            lm.LED_MASTER_FILE = orig_master
            del rfid_map["TEST_UID"]
        assert source == "rfid"
        assert assignment["effect_id"] == "breathing"

    def test_fallback_to_default_when_rfid_led_disabled(self):
        from api.led import get_effective_led_assignment, DEFAULT_LED_ASSIGNMENT
        from core.state import led_runtime, rfid_map
        import api.led as lm
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_master = lm.LED_MASTER_FILE
            lm.LED_MASTER_FILE = os.path.join(tmpdir, "master.json")
            master_data = {
                "enabled": True, "override_active": False,
                "settings": {"effect_id": "solid", "color": "#0000ff",
                             "brightness": 70, "speed": 30, "params": {}},
            }
            with open(lm.LED_MASTER_FILE, "w") as f:
                json.dump(master_data, f)
            rfid_map["UID2"] = {
                "type": "audio",
                "target": "/test.mp3",
                "led": {"enabled": False, "effect_id": "rainbow",
                        "color": "#ff0000", "brightness": 80, "speed": 50, "params": {}},
            }
            led_runtime["ai_state"] = None
            led_runtime["current_rfid"] = "UID2"
            assignment, source = get_effective_led_assignment()
            lm.LED_MASTER_FILE = orig_master
            del rfid_map["UID2"]
        assert source == "default"
        assert assignment["effect_id"] == DEFAULT_LED_ASSIGNMENT["effect_id"]


# ===========================================================================
# G) _migrate_master — migrazione dal vecchio formato flat
# ===========================================================================

class TestMigrateMaster:

    def test_flat_format_migrated_to_nested(self):
        from api.led import _migrate_master
        old = {
            "enabled": True,
            "effect_id": "rainbow",
            "color": "#ff9900",
            "brightness": 75,
            "speed": 45,
            "override": True,
            "params": {},
        }
        result = _migrate_master(old)
        assert "settings" in result
        assert result["override_active"] is True
        assert result["settings"]["effect_id"] == "rainbow"

    def test_new_format_unchanged(self):
        from api.led import _migrate_master
        new = {
            "enabled": True,
            "override_active": False,
            "settings": {"effect_id": "solid", "color": "#0000ff",
                         "brightness": 70, "speed": 30, "params": {}},
        }
        result = _migrate_master(new)
        assert result["settings"]["effect_id"] == "solid"
        assert result["override_active"] is False

    def test_old_override_key_renamed(self):
        from api.led import _migrate_master
        data = {
            "enabled": True,
            "override_active": True,
            "settings": {"effect_id": "pulse", "color": "#ff0000",
                         "brightness": 80, "speed": 60, "params": {}},
        }
        result = _migrate_master(data)
        assert result["override_active"] is True
        assert "override" not in result


# ===========================================================================
# H) Custom effects CRUD (logica — senza Flask client)
# ===========================================================================

class TestCustomEffectsCrud:

    def test_save_and_load_custom_effect(self):
        from api.led import load_custom_led_effects
        with tempfile.TemporaryDirectory() as tmpdir:
            effect = {"id": "my_test_eff", "name": "My Test", "builtin": False}
            fpath = os.path.join(tmpdir, "my_test_eff.json")
            with open(fpath, "w") as f:
                json.dump(effect, f)
            orig = _tmp_custom_dir(tmpdir)
            effects = load_custom_led_effects()
            led_module.LED_EFFECTS_CUSTOM_DIR = orig
        assert "my_test_eff" in effects

    def test_invalid_json_skipped(self):
        from api.led import load_custom_led_effects
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "broken.json")
            with open(fpath, "w") as f:
                f.write("{bad json")
            orig = _tmp_custom_dir(tmpdir)
            effects = load_custom_led_effects()
            led_module.LED_EFFECTS_CUSTOM_DIR = orig
        assert len(effects) == 0

    def test_get_all_effects_includes_builtin_and_custom(self):
        from api.led import _get_all_effects, BUILTIN_LED_EFFECTS
        with tempfile.TemporaryDirectory() as tmpdir:
            effect = {"id": "custom_one", "name": "Custom 1", "builtin": False}
            fpath = os.path.join(tmpdir, "custom_one.json")
            with open(fpath, "w") as f:
                json.dump(effect, f)
            orig = _tmp_custom_dir(tmpdir)
            all_effects = _get_all_effects()
            led_module.LED_EFFECTS_CUSTOM_DIR = orig
        for builtin_id in BUILTIN_LED_EFFECTS:
            assert builtin_id in all_effects
        assert "custom_one" in all_effects

    def test_sequence_effect_saved_and_loaded(self):
        from api.led import load_custom_led_effects
        with tempfile.TemporaryDirectory() as tmpdir:
            effect = {
                "id": "my_sequence",
                "name": "My Sequence",
                "type": "sequence",
                "steps": [
                    {"effect_id": "solid", "duration_ms": 500},
                    {"effect_id": "breathing", "duration_ms": 800},
                ],
                "builtin": False,
            }
            fpath = os.path.join(tmpdir, "my_sequence.json")
            with open(fpath, "w") as f:
                json.dump(effect, f)
            orig = _tmp_custom_dir(tmpdir)
            effects = load_custom_led_effects()
            led_module.LED_EFFECTS_CUSTOM_DIR = orig
        assert "my_sequence" in effects
        assert effects["my_sequence"]["type"] == "sequence"


# ===========================================================================
# I) Smoke tests HTTP endpoints LED
# ===========================================================================

@pytest.fixture
def client():
    """Flask test client for LED endpoint smoke tests."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.led import led_bp
    from api.media import media_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret-key"
    flask_app.config["TESTING"] = True
    CORS(flask_app, supports_credentials=True)
    flask_app.register_blueprint(led_bp, url_prefix="/api")
    flask_app.register_blueprint(media_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    with flask_app.test_client() as c:
        yield c


class TestLedEndpointsSmoke:

    def test_get_effects(self, client):
        resp = client.get("/api/led/effects")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "effects" in data
        effect_ids = [e["id"] for e in data["effects"]]
        for bid in ("off", "solid", "breathing", "blink", "rainbow", "pulse", "random"):
            assert bid in effect_ids

    def test_get_master(self, client):
        resp = client.get("/api/led/master")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "settings" in data
        assert "override_active" in data

    def test_post_master_nested_format(self, client):
        resp = client.post("/api/led/master", json={
            "enabled": True,
            "override_active": False,
            "settings": {
                "effect_id": "breathing",
                "color": "#00ff88",
                "brightness": 60,
                "speed": 40,
                "params": {},
            },
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["master"]["settings"]["effect_id"] == "breathing"

    def test_post_master_flat_format_backward_compat(self, client):
        resp = client.post("/api/led/master", json={
            "effect_id": "pulse",
            "color": "#ff9900",
            "brightness": 75,
            "speed": 50,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_post_master_invalid_effect(self, client):
        resp = client.post("/api/led/master", json={
            "settings": {"effect_id": "nonexistent_effect_xyz",
                         "color": "#ff0000", "brightness": 50, "speed": 30}
        })
        assert resp.status_code == 400

    def test_post_master_invalid_color(self, client):
        resp = client.post("/api/led/master", json={
            "settings": {"effect_id": "solid", "color": "notacolor",
                         "brightness": 50, "speed": 30}
        })
        assert resp.status_code == 400

    def test_post_master_override(self, client):
        resp = client.post("/api/led/master/override", json={"override_active": True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["override_active"] is True

    def test_post_master_override_compat_key(self, client):
        resp = client.post("/api/led/master/override", json={"override": False})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["override_active"] is False

    def test_get_status(self, client):
        resp = client.get("/api/led/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "runtime" in data
        assert "master" in data
        assert "override_active" in data
        assert "current_source" in data
        assert "applied" in data

    def test_post_effects_custom(self, client):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = _tmp_custom_dir(tmpdir)
            resp = client.post("/api/led/effects", json={"id": "http_custom", "name": "HTTP Custom"})
            led_module.LED_EFFECTS_CUSTOM_DIR = orig
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["effect_id"] == "http_custom"

    def test_post_effects_builtin_id_rejected(self, client):
        resp = client.post("/api/led/effects", json={"id": "rainbow", "name": "My Rainbow"})
        assert resp.status_code == 400

    def test_delete_builtin_effect_rejected(self, client):
        resp = client.delete("/api/led/effects/solid")
        assert resp.status_code == 400

    def test_effects_test_endpoint(self, client):
        resp = client.post("/api/led/effects/test", json={
            "effect_id": "rainbow",
            "color": "#ff0000",
            "brightness": 80,
            "speed": 50,
        })
        assert resp.status_code == 200

    def test_effects_test_invalid_effect(self, client):
        resp = client.post("/api/led/effects/test", json={"effect_id": "nonexistent_xyz"})
        assert resp.status_code == 404

    def test_ai_state_endpoint_valid(self, client):
        resp = client.post("/api/led/ai_state", json={"state": "listening"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ai_state"] == "listening"

    def test_ai_state_endpoint_reset(self, client):
        resp = client.post("/api/led/ai_state", json={"state": None})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ai_state"] is None

    def test_ai_state_endpoint_invalid(self, client):
        resp = client.post("/api/led/ai_state", json={"state": "dancing"})
        assert resp.status_code == 400


# ===========================================================================
# J) RFID trigger → LED runtime integration
# ===========================================================================

class TestRfidLedIntegration:

    def setup_method(self):
        from core.state import led_runtime, DEFAULT_LED_RUNTIME
        led_runtime.clear()
        led_runtime.update(copy.deepcopy(DEFAULT_LED_RUNTIME))

    def test_rfid_trigger_sets_current_rfid(self, client):
        from unittest.mock import patch
        from core.state import rfid_map, led_runtime
        rfid_map["RFID_LED_TEST"] = {
            "type": "audio",
            "target": "/music/test.mp3",
            "led": {
                "enabled": True,
                "effect_id": "pulse",
                "color": "#ff00aa",
                "brightness": 70,
                "speed": 40,
                "params": {},
            },
        }
        with patch("api.media.start_player", return_value=(True, "ok")):
            resp = client.post("/api/rfid/trigger", json={"rfid_code": "RFID_LED_TEST"})
        assert resp.status_code == 200
        assert led_runtime.get("current_rfid") == "RFID_LED_TEST"
        del rfid_map["RFID_LED_TEST"]

    def test_rfid_delete_clears_current_rfid(self, client):
        from core.state import rfid_map, led_runtime
        rfid_map["DEL_TEST"] = {"type": "audio", "target": "/x.mp3"}
        led_runtime["current_rfid"] = "DEL_TEST"
        resp = client.post("/api/rfid/delete", json={"uid": "DEL_TEST"})
        assert resp.status_code == 200
        assert led_runtime.get("current_rfid") is None
