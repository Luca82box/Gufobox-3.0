"""
Test base per config.py — verifica che le costanti chiave siano esposte
e abbiano i tipi attesi. Non richiede hardware reale.
"""
import config


def test_file_manager_default_path_exists():
    assert hasattr(config, "FILE_MANAGER_DEFAULT_PATH")
    assert isinstance(config.FILE_MANAGER_DEFAULT_PATH, str)
    assert len(config.FILE_MANAGER_DEFAULT_PATH) > 0


def test_ai_settings_file_exists():
    assert hasattr(config, "AI_SETTINGS_FILE")
    assert isinstance(config.AI_SETTINGS_FILE, str)
    assert config.AI_SETTINGS_FILE.endswith(".json")


def test_rfid_map_file_exists():
    assert hasattr(config, "RFID_MAP_FILE")
    assert isinstance(config.RFID_MAP_FILE, str)


def test_secret_key_has_default():
    assert hasattr(config, "SECRET_KEY")
    assert isinstance(config.SECRET_KEY, str)
    assert len(config.SECRET_KEY) > 0


def test_api_version_is_string():
    assert hasattr(config, "API_VERSION")
    assert isinstance(config.API_VERSION, str)
