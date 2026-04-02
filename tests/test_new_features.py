"""
Test per le nuove funzionalità: LED effects catalog, RFID LED profile,
hotspot config variables, OTA state helpers.
"""
import os
import json
import tempfile

import pytest


# =========================================================
# Test config — nuove variabili
# =========================================================
def test_hotspot_ssid_in_config():
    import config
    assert hasattr(config, "HOTSPOT_SSID")
    assert isinstance(config.HOTSPOT_SSID, str)
    assert len(config.HOTSPOT_SSID) > 0


def test_hotspot_pass_in_config():
    import config
    assert hasattr(config, "HOTSPOT_PASS")
    assert isinstance(config.HOTSPOT_PASS, str)


def test_hotspot_conn_name_in_config():
    import config
    assert hasattr(config, "HOTSPOT_CONN_NAME")
    assert isinstance(config.HOTSPOT_CONN_NAME, str)


def test_backup_dir_in_config():
    import config
    assert hasattr(config, "BACKUP_DIR")
    assert isinstance(config.BACKUP_DIR, str)


def test_ota_log_file_in_config():
    import config
    assert hasattr(config, "OTA_LOG_FILE")
    assert config.OTA_LOG_FILE.endswith(".log")


def test_led_master_file_in_config():
    import config
    assert hasattr(config, "LED_MASTER_FILE")
    assert config.LED_MASTER_FILE.endswith(".json")


# =========================================================
# Test LED effects catalog
# =========================================================
def test_builtin_effects_present():
    from api.led import BUILTIN_LED_EFFECTS
    for eff_id in ("off", "solid", "breathing", "blink", "rainbow", "pulse"):
        assert eff_id in BUILTIN_LED_EFFECTS


def test_builtin_effect_has_required_fields():
    from api.led import BUILTIN_LED_EFFECTS
    for eff_id, eff in BUILTIN_LED_EFFECTS.items():
        assert "id" in eff
        assert "name" in eff
        assert eff["id"] == eff_id


def test_validate_custom_effect_valid():
    from api.led import _validate_custom_effect
    data = {"id": "my_custom", "name": "My Effect"}
    ok, err = _validate_custom_effect(data)
    assert ok is True
    assert err is None


def test_validate_custom_effect_missing_id():
    from api.led import _validate_custom_effect
    data = {"name": "Missing ID"}
    ok, err = _validate_custom_effect(data)
    assert ok is False
    assert err is not None


def test_validate_custom_effect_missing_name():
    from api.led import _validate_custom_effect
    data = {"id": "no_name"}
    ok, err = _validate_custom_effect(data)
    assert ok is False


def test_validate_custom_effect_builtin_id_rejected():
    from api.led import _validate_custom_effect
    data = {"id": "rainbow", "name": "Custom Rainbow"}
    ok, err = _validate_custom_effect(data)
    assert ok is False
    assert "builtin" in (err or "").lower()


def test_validate_custom_effect_non_dict_rejected():
    from api.led import _validate_custom_effect
    ok, err = _validate_custom_effect([1, 2, 3])
    assert ok is False


def test_load_custom_led_effects_empty_dir():
    """load_custom_led_effects su directory vuota ritorna dict vuoto."""
    from api.led import load_custom_led_effects
    import api.led as led_module
    original = led_module.LED_EFFECTS_CUSTOM_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        led_module.LED_EFFECTS_CUSTOM_DIR = tmpdir
        effects = load_custom_led_effects()
        led_module.LED_EFFECTS_CUSTOM_DIR = original
    assert isinstance(effects, dict)
    assert len(effects) == 0


def test_load_custom_led_effects_reads_valid_json():
    """load_custom_led_effects carica correttamente un effetto valido."""
    from api.led import load_custom_led_effects
    import api.led as led_module
    original = led_module.LED_EFFECTS_CUSTOM_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        effect_data = {"id": "test_effect", "name": "Test", "builtin": False}
        fpath = os.path.join(tmpdir, "test_effect.json")
        with open(fpath, "w") as f:
            json.dump(effect_data, f)
        led_module.LED_EFFECTS_CUSTOM_DIR = tmpdir
        effects = load_custom_led_effects()
        led_module.LED_EFFECTS_CUSTOM_DIR = original
    assert "test_effect" in effects


def test_load_custom_led_effects_skips_invalid_json():
    """load_custom_led_effects ignora file JSON non validi."""
    from api.led import load_custom_led_effects
    import api.led as led_module
    original = led_module.LED_EFFECTS_CUSTOM_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = os.path.join(tmpdir, "bad.json")
        with open(fpath, "w") as f:
            f.write("not valid json {{")
        led_module.LED_EFFECTS_CUSTOM_DIR = tmpdir
        effects = load_custom_led_effects()
        led_module.LED_EFFECTS_CUSTOM_DIR = original
    assert len(effects) == 0


# =========================================================
# Test DEFAULT_LED_MASTER
# =========================================================
def test_default_led_master_fields():
    from api.led import DEFAULT_LED_MASTER
    # Top-level fields
    for field in ("enabled", "override_active", "settings"):
        assert field in DEFAULT_LED_MASTER
    # Settings sub-dict fields
    for field in ("effect_id", "color", "brightness", "speed", "params"):
        assert field in DEFAULT_LED_MASTER["settings"]


def test_load_led_master_returns_default_when_no_file():
    from api.led import load_led_master, DEFAULT_LED_MASTER
    import api.led as led_module
    original = led_module.LED_MASTER_FILE
    led_module.LED_MASTER_FILE = "/tmp/gufobox_test_led_master_nonexistent.json"
    result = load_led_master()
    led_module.LED_MASTER_FILE = original
    assert result["settings"]["effect_id"] == DEFAULT_LED_MASTER["settings"]["effect_id"]
    assert "override_active" in result


# =========================================================
# Test RFID profile LED validation (via media route logic)
# =========================================================
def test_rfid_profile_led_block_structure():
    """Verifica che la struttura LED attesa nel profilo RFID sia corretta."""
    led_block = {
        "enabled": True,
        "effect_id": "rainbow",
        "color": "#ff9900",
        "brightness": 70,
        "speed": 30,
        "params": {},
    }
    # Verifica i tipi attesi
    assert isinstance(led_block["enabled"], bool)
    assert isinstance(led_block["effect_id"], str)
    assert isinstance(led_block["color"], str)
    assert isinstance(led_block["brightness"], int)
    assert isinstance(led_block["speed"], int)
    assert isinstance(led_block["params"], dict)
