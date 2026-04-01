"""
Test base per api/network.py — verifica le funzioni helper Bluetooth
che non richiedono hardware reale.
"""
from api.network import _parse_bt_device_line


def test_parse_bt_device_line_valid():
    line = "Device AA:BB:CC:DD:EE:FF My Speaker"
    result = _parse_bt_device_line(line)
    assert result is not None
    assert result["mac"] == "AA:BB:CC:DD:EE:FF"
    assert result["name"] == "My Speaker"


def test_parse_bt_device_line_no_name_fallback_to_mac():
    """Se il nome non è presente, il MAC viene usato come fallback."""
    line = "Device 11:22:33:44:55:66"
    result = _parse_bt_device_line(line)
    assert result is not None
    assert result["mac"] == "11:22:33:44:55:66"
    assert result["name"] == "11:22:33:44:55:66"


def test_parse_bt_device_line_invalid_returns_none():
    """Linee non valide devono ritornare None."""
    assert _parse_bt_device_line("") is None
    assert _parse_bt_device_line("some random text") is None
    assert _parse_bt_device_line("Controller 00:11:22:33:44:55 gufobox") is None


def test_parse_bt_device_line_empty_name_fallback():
    """Se il nome è una stringa vuota, usa il MAC come fallback."""
    line = "Device FF:EE:DD:CC:BB:AA  "
    result = _parse_bt_device_line(line)
    assert result is not None
    assert result["name"] == result["mac"]
