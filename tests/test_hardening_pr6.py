"""
tests/test_hardening_pr6.py — PR 6: Hardening & Release Readiness

Covers:
A) Standby state machine (awake / standby / waking / alarm_active)
   - State constants exposed
   - perform_standby sets STANDBY_STANDBY
   - wake_from_standby transitions through WAKING then AWAKE
   - is_in_standby backward compat
   - get_standby_state returns string
   - _alarm_worker debounce (same minute → only fires once)
   - _alarm_worker sets alarm_active state, then awake
   - _wake_for_alarm reinitializes amp/LED
   - GET /system/standby exposes standby_state field

B) Bluetooth hardening
   - _validate_mac_address: valid/invalid formats
   - _parse_bt_controller_status: fields correctly parsed
   - api_bluetooth_toggle uses correct command list (not string)
   - pair/connect/forget return 400 for invalid MAC
   - bluetooth status includes controller_available, powered, discoverable, pairable
   - bluetoothctl appears in /diag/tools

C) Diagnostics readiness
   - /diag/summary includes standby_state
   - /diag/summary includes readiness dict with sub-keys
   - readiness helpers return correct structure
   - _readiness_audio returns ok/mpv/amixer/aplay/note
   - _readiness_bluetooth returns ok/bluetoothctl/rfkill/controller_available/note
   - _readiness_network returns ok/nmcli/note
   - _readiness_standby_alarm returns ok/vcgencmd/cpufreq_set/note
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def system_app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.system import system_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(system_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def system_client(system_app):
    with system_app.test_client() as c:
        yield c


@pytest.fixture()
def network_app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.network import network_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(network_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def network_client(network_app):
    with network_app.test_client() as c:
        yield c


@pytest.fixture()
def diag_app():
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.diag import diag_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(diag_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def diag_client(diag_app):
    with diag_app.test_client() as c:
        yield c


# ─── A) Standby state machine ─────────────────────────────────────────────────

class TestStandbyStateMachine:

    def test_standby_constants_defined(self):
        """State constants must be importable and correct."""
        from core.hardware import (
            STANDBY_AWAKE, STANDBY_STANDBY, STANDBY_WAKING, STANDBY_ALARM_ACTIVE,
        )
        assert STANDBY_AWAKE == "awake"
        assert STANDBY_STANDBY == "standby"
        assert STANDBY_WAKING == "waking"
        assert STANDBY_ALARM_ACTIVE == "alarm_active"

    def test_initial_state_is_awake(self):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_AWAKE
        assert hw.get_standby_state() == "awake"
        assert hw.is_in_standby() is False

    def test_is_in_standby_backward_compat_true(self):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        assert hw.is_in_standby() is True

    def test_is_in_standby_backward_compat_false_when_waking(self):
        """is_in_standby() must be False during WAKING (it's not fully standby anymore)."""
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_WAKING
        assert hw.is_in_standby() is False

    def test_get_standby_state_returns_current(self):
        import core.hardware as hw
        for state in ("awake", "standby", "waking", "alarm_active"):
            hw._standby_state = state
            assert hw.get_standby_state() == state

    def test_perform_standby_sets_standby_state(self):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_AWAKE
        with patch("core.hardware.run_cmd"), \
             patch("core.hardware.amp_off"), \
             patch("core.hardware.eventlet") as mock_ev, \
             patch("core.media.stop_player"), \
             patch("hw.battery.play_ai_notification"), \
             patch.object(hw.bus, "emit_notification"), \
             patch.object(hw.bus, "request_emit"), \
             patch.object(hw.bus, "mark_dirty"):
            mock_ev.sleep = MagicMock()
            hw.perform_standby()
        assert hw._standby_state == hw.STANDBY_STANDBY
        assert hw.is_in_standby() is True

    def test_perform_standby_idempotent_when_already_in_standby(self):
        """Calling perform_standby when already standby should be a no-op."""
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        with patch("core.hardware.amp_off") as mock_amp:
            hw.perform_standby()
        mock_amp.assert_not_called()
        assert hw._standby_state == hw.STANDBY_STANDBY

    def test_wake_from_standby_sets_awake(self):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        with patch("core.hardware.run_cmd"), \
             patch("core.hardware.amp_on"), \
             patch("hw.battery.play_ai_notification"):
            hw.wake_from_standby()
        assert hw._standby_state == hw.STANDBY_AWAKE
        assert hw.is_in_standby() is False

    def test_wake_from_standby_idempotent_when_awake(self):
        """Calling wake_from_standby when already awake should be a no-op."""
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_AWAKE
        with patch("core.hardware.amp_on") as mock_amp:
            hw.wake_from_standby()
        mock_amp.assert_not_called()

    def test_wake_for_alarm_sets_alarm_active(self):
        """_wake_for_alarm must transition to alarm_active state."""
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        with patch("core.hardware.run_cmd"), \
             patch("core.hardware.amp_on"):
            hw._wake_for_alarm()
        assert hw._standby_state == hw.STANDBY_ALARM_ACTIVE

    def test_wake_for_alarm_calls_amp_on(self):
        """_wake_for_alarm must call amp_on to prevent silent alarm."""
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        with patch("core.hardware.run_cmd"), \
             patch("core.hardware.amp_on") as mock_amp:
            hw._wake_for_alarm()
        mock_amp.assert_called_once()

    def test_alarm_worker_debounce_fires_once_per_minute(self):
        """Same alarm+minute must not fire twice."""
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_AWAKE
        hw._alarm_last_fired.clear()

        from datetime import datetime
        fixed_now = datetime(2026, 1, 5, 7, 30, 0)  # Monday

        alarm = {"enabled": True, "hour": 7, "minute": 30,
                 "days": list(range(7)), "target": "alarm.mp3", "id": "alarm-1"}

        start_calls = {"n": 0}
        wake_calls = {"n": 0}

        sleep_calls = {"n": 0}

        def _mock_sleep(*args):
            sleep_calls["n"] += 1
            if sleep_calls["n"] > 2:
                raise StopIteration

        with patch("core.hardware.datetime") as mock_dt, \
             patch("core.hardware.alarms_list", [alarm]), \
             patch("core.hardware.eventlet") as mock_ev, \
             patch("core.hardware._wake_for_alarm", side_effect=lambda: wake_calls.__setitem__("n", wake_calls["n"] + 1)), \
             patch("core.media.start_player", side_effect=lambda *a, **k: start_calls.__setitem__("n", start_calls["n"] + 1)), \
             patch.object(hw.bus, "emit_notification"), \
             patch.object(hw.bus, "request_emit"):
            mock_dt.now.return_value = fixed_now
            mock_ev.sleep = MagicMock(side_effect=_mock_sleep)
            try:
                hw._alarm_worker()
            except StopIteration:
                pass

        # Alarm should have fired exactly once despite 2 loop iterations
        assert wake_calls["n"] == 1, f"wake calls: {wake_calls['n']}, expected 1"
        assert start_calls["n"] == 1, f"start_player calls: {start_calls['n']}, expected 1"

    def test_standby_status_endpoint_has_standby_state(self, system_client):
        """GET /api/system/standby must return both in_standby and standby_state."""
        rv = system_client.get("/api/system/standby")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "in_standby" in data
        assert "standby_state" in data
        assert isinstance(data["in_standby"], bool)
        assert isinstance(data["standby_state"], str)

    def test_standby_state_reflects_current_value(self, system_client):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        rv = system_client.get("/api/system/standby")
        data = rv.get_json()
        assert data["standby_state"] == "standby"
        assert data["in_standby"] is True
        # Cleanup
        hw._standby_state = hw.STANDBY_AWAKE


# ─── B) Bluetooth hardening ───────────────────────────────────────────────────

class TestBluetoothMacValidation:

    def test_valid_mac_addresses(self):
        from api.network import _validate_mac_address
        valid = [
            "AA:BB:CC:DD:EE:FF",
            "aa:bb:cc:dd:ee:ff",
            "00:11:22:33:44:55",
            "A1:B2:C3:D4:E5:F6",
        ]
        for mac in valid:
            assert _validate_mac_address(mac) is True, f"Should be valid: {mac}"

    def test_invalid_mac_addresses(self):
        from api.network import _validate_mac_address
        invalid = [
            "",
            None,
            "not-a-mac",
            "AA:BB:CC:DD:EE",        # 5 groups
            "AA:BB:CC:DD:EE:FF:GG",  # 7 groups
            "AA:BB:CC:DD:EE:XY",     # invalid hex
            "AABBCCDDEEFF",          # no colons
            "../../../etc/passwd",    # path traversal
        ]
        for mac in invalid:
            assert _validate_mac_address(mac) is False, f"Should be invalid: {mac}"


class TestParseBluetoothControllerStatus:

    def test_parse_powered_yes(self):
        from api.network import _parse_bt_controller_status
        stdout = """Controller AA:BB:CC:DD:EE:FF (public)
\tName: gufobox
\tAlias: GufoBox
\tPowered: yes
\tDiscoverable: no
\tPairable: yes
"""
        result = _parse_bt_controller_status(stdout)
        assert result["available"] is True
        assert result["powered"] is True
        assert result["discoverable"] is False
        assert result["pairable"] is True
        assert result["address"] == "AA:BB:CC:DD:EE:FF"
        assert result["name"] == "gufobox"

    def test_parse_powered_no(self):
        from api.network import _parse_bt_controller_status
        stdout = "Controller 00:11:22:33:44:55 (public)\n\tPowered: no\n\tDiscoverable: no\n\tPairable: no\n"
        result = _parse_bt_controller_status(stdout)
        assert result["available"] is True
        assert result["powered"] is False
        assert result["discoverable"] is False
        assert result["pairable"] is False

    def test_parse_empty_string_not_available(self):
        from api.network import _parse_bt_controller_status
        result = _parse_bt_controller_status("")
        assert result["available"] is False
        assert result["powered"] is False

    def test_parse_none_not_available(self):
        from api.network import _parse_bt_controller_status
        result = _parse_bt_controller_status(None)
        assert result["available"] is False

    def test_parse_all_yes(self):
        from api.network import _parse_bt_controller_status
        stdout = (
            "Controller FF:EE:DD:CC:BB:AA (public)\n"
            "\tName: test\n"
            "\tPowered: yes\n"
            "\tDiscoverable: yes\n"
            "\tPairable: yes\n"
        )
        result = _parse_bt_controller_status(stdout)
        assert result["powered"] is True
        assert result["discoverable"] is True
        assert result["pairable"] is True
        assert result["address"] == "FF:EE:DD:CC:BB:AA"


class TestBluetoothToggleFix:
    """Verify that toggle uses list args (not string 'power on')."""

    def test_toggle_on_uses_correct_command(self, network_client):
        captured = []

        def mock_run_cmd(cmd, **kwargs):
            captured.append(cmd)
            return (0, "", "")

        with patch("api.network.run_cmd", side_effect=mock_run_cmd):
            rv = network_client.post(
                "/api/bluetooth/toggle",
                json={"enabled": True},
                content_type="application/json",
            )
        assert rv.status_code == 200
        assert len(captured) == 1
        # Must be a proper list, not a string
        assert isinstance(captured[0], list)
        assert captured[0] == ["bluetoothctl", "power", "on"]

    def test_toggle_off_uses_correct_command(self, network_client):
        captured = []

        def mock_run_cmd(cmd, **kwargs):
            captured.append(cmd)
            return (0, "", "")

        with patch("api.network.run_cmd", side_effect=mock_run_cmd):
            rv = network_client.post(
                "/api/bluetooth/toggle",
                json={"enabled": False},
                content_type="application/json",
            )
        assert rv.status_code == 200
        assert captured[0] == ["bluetoothctl", "power", "off"]


class TestBluetoothMacValidationInRoutes:

    def test_pair_invalid_mac_returns_400(self, network_client):
        rv = network_client.post(
            "/api/bluetooth/pair",
            json={"mac": "not-a-mac"},
            content_type="application/json",
        )
        assert rv.status_code == 400
        data = rv.get_json()
        assert "error" in data

    def test_connect_invalid_mac_returns_400(self, network_client):
        rv = network_client.post(
            "/api/bluetooth/connect",
            json={"mac": "INVALID"},
            content_type="application/json",
        )
        assert rv.status_code == 400

    def test_forget_invalid_mac_returns_400(self, network_client):
        rv = network_client.post(
            "/api/bluetooth/forget",
            json={"mac": "../etc/passwd"},
            content_type="application/json",
        )
        assert rv.status_code == 400

    def test_pair_path_traversal_returns_400(self, network_client):
        rv = network_client.post(
            "/api/bluetooth/pair",
            json={"mac": "../../etc/shadow"},
            content_type="application/json",
        )
        assert rv.status_code == 400


class TestBluetoothStatusEnrichedFields:

    def test_status_has_controller_fields(self, network_client):
        def mock_run_cmd(cmd, **kwargs):
            if cmd == ["bluetoothctl", "show"]:
                return (0, "Controller AA:BB:CC:DD:EE:FF (public)\n\tPowered: no\n\tDiscoverable: no\n\tPairable: no\n", "")
            if cmd == ["bluetoothctl", "paired-devices"]:
                return (0, "", "")
            return (0, "", "")

        with patch("api.network.run_cmd", side_effect=mock_run_cmd):
            rv = network_client.get("/api/bluetooth/status")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "controller_available" in data
        assert "powered" in data
        assert "discoverable" in data
        assert "pairable" in data
        assert isinstance(data["controller_available"], bool)

    def test_status_controller_not_available_when_cmd_fails(self, network_client):
        with patch("api.network.run_cmd", return_value=(1, "", "bluetoothctl not found")):
            rv = network_client.get("/api/bluetooth/status")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data["controller_available"] is False
        assert data["enabled"] is False


class TestBluetoothctlInDiagTools:

    def test_bluetoothctl_in_tools_list(self, diag_client):
        rv = diag_client.get("/api/diag/tools")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "bluetoothctl" in data["tools"]
        assert isinstance(data["tools"]["bluetoothctl"], bool)


# ─── C) Diagnostics readiness ─────────────────────────────────────────────────

class TestDiagReadinessHelpers:

    def test_readiness_audio_structure(self):
        from api.diag import _readiness_audio
        result = _readiness_audio()
        assert "ok" in result
        assert "mpv" in result
        assert "amixer" in result
        assert "aplay" in result
        assert "note" in result
        assert isinstance(result["ok"], bool)

    def test_readiness_audio_ok_requires_mpv_and_amixer(self):
        from api.diag import _readiness_audio
        with patch("api.diag._check_tool", side_effect=lambda t: t in ("mpv", "amixer", "aplay")):
            result = _readiness_audio()
        assert result["ok"] is True
        assert result["mpv"] is True
        assert result["amixer"] is True

    def test_readiness_audio_not_ok_when_mpv_missing(self):
        from api.diag import _readiness_audio
        with patch("api.diag._check_tool", return_value=False):
            result = _readiness_audio()
        assert result["ok"] is False
        assert result["note"] is not None

    def test_readiness_bluetooth_structure(self):
        from api.diag import _readiness_bluetooth
        with patch("api.diag.run_cmd", return_value=(1, "", "")):
            result = _readiness_bluetooth()
        assert "ok" in result
        assert "bluetoothctl" in result
        assert "rfkill" in result
        assert "controller_available" in result
        assert "note" in result

    def test_readiness_bluetooth_no_tool(self):
        from api.diag import _readiness_bluetooth
        with patch("api.diag._check_tool", return_value=False):
            result = _readiness_bluetooth()
        assert result["ok"] is False
        assert result["bluetoothctl"] is False
        assert result["note"] is not None

    def test_readiness_bluetooth_tool_present_no_controller(self):
        from api.diag import _readiness_bluetooth
        with patch("api.diag._check_tool", side_effect=lambda t: t in ("bluetoothctl", "rfkill")), \
             patch("api.diag.run_cmd", return_value=(1, "", "no controller")):
            result = _readiness_bluetooth()
        assert result["bluetoothctl"] is True
        assert result["controller_available"] is False
        assert result["ok"] is False

    def test_readiness_network_structure(self):
        from api.diag import _readiness_network
        result = _readiness_network()
        assert "ok" in result
        assert "nmcli" in result
        assert "note" in result

    def test_readiness_standby_alarm_structure(self):
        from api.diag import _readiness_standby_alarm
        result = _readiness_standby_alarm()
        assert "ok" in result
        assert "vcgencmd" in result
        assert "cpufreq_set" in result
        assert "note" in result

    def test_readiness_standby_alarm_note_when_tools_absent(self):
        from api.diag import _readiness_standby_alarm
        with patch("api.diag._check_tool", return_value=False):
            result = _readiness_standby_alarm()
        assert result["ok"] is False
        assert result["note"] is not None


class TestDiagSummaryReadinessFields:

    def test_summary_has_standby_state_field(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "standby_state" in data
        assert isinstance(data["standby_state"], str)

    def test_summary_has_readiness_field(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "readiness" in data
        readiness = data["readiness"]
        assert "audio" in readiness
        assert "bluetooth" in readiness
        assert "network" in readiness
        assert "standby_alarm" in readiness

    def test_summary_readiness_audio_has_ok(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        audio = rv.get_json()["readiness"]["audio"]
        assert "ok" in audio
        assert isinstance(audio["ok"], bool)

    def test_summary_readiness_bluetooth_has_ok(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        bt = rv.get_json()["readiness"]["bluetooth"]
        assert "ok" in bt
        assert "controller_available" in bt

    def test_summary_readiness_does_not_crash_in_ci(self, diag_client):
        """readiness helpers must not raise in non-RPi environments."""
        rv = diag_client.get("/api/diag/summary")
        assert rv.status_code == 200
