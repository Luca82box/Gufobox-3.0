"""
Test base per core/state.py — verifica load_json con file inesistente
e salvataggio/lettura su file temporaneo. Non richiede hardware reale.
"""
import os
import tempfile

from core.state import load_json, save_json_direct


def test_load_json_missing_file_returns_default():
    """Se il file non esiste, load_json deve ritornare il default."""
    default = {"key": "value", "num": 42}
    result = load_json("/tmp/gufobox_test_nonexistent_xyz.json", default)
    assert result == default


def test_load_json_missing_file_does_not_modify_default():
    """Il default non deve essere mutato (deve essere una copia profonda)."""
    default = {"nested": {"a": 1}}
    result = load_json("/tmp/gufobox_test_nonexistent_xyz.json", default)
    result["nested"]["a"] = 99
    assert default["nested"]["a"] == 1  # Il default originale è intatto


def test_save_and_load_json_roundtrip():
    """save_json_direct + load_json deve fare un roundtrip senza perdita di dati."""
    data = {"player_running": False, "volume": 75, "mode": "audio_only"}
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_json_direct(path, data)
        loaded = load_json(path, {})
        assert loaded == data
    finally:
        os.unlink(path)
        tmp = f"{path}.tmp"
        if os.path.exists(tmp):
            os.unlink(tmp)


def test_load_json_invalid_file_returns_default():
    """Se il file contiene JSON non valido, ritorna il default senza crash."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not valid json {{{")
        path = f.name
    try:
        default = {"fallback": True}
        result = load_json(path, default)
        assert result == default
    finally:
        os.unlink(path)
