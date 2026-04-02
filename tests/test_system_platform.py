"""
tests/test_system_platform.py — PR 4: System Platform

Covers:
- OTA state helpers: default fields, running flag, schema migration
- Backup name sanitization / path-traversal safety
- Rollback safety (unknown backup returns 404)
- Power/system action validation (reboot/shutdown/standby)
- Standby state logic at application level
- POST /api/network/scan alias
- POST /api/bluetooth/unblock and /api/bluetooth/pair
- GET /api/diag/summary enriched fields (api_version, ip, ota_status, backup_count, standby)
"""

import json
import os
import sys
import threading
import tempfile
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Shared app fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def system_app(tmp_path):
    """Flask app with system_bp and a temporary data directory."""
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


# ─── A) OTA state helpers ─────────────────────────────────────────────────────

class TestOtaStateHelpers:

    def test_load_ota_state_returns_all_required_fields(self, tmp_path):
        """_load_ota_state must return running, status, progress_percent, description, last_error."""
        from api.system import _load_ota_state, OTA_STATE_FILE
        import api.system as sys_mod

        original = sys_mod.OTA_STATE_FILE
        sys_mod.OTA_STATE_FILE = str(tmp_path / "ota_state.json")
        try:
            state = _load_ota_state()
            for key in ("running", "status", "mode", "started_at", "finished_at",
                        "progress_percent", "description", "error", "last_error"):
                assert key in state, f"Campo mancante: {key}"
        finally:
            sys_mod.OTA_STATE_FILE = original

    def test_load_ota_state_idle_by_default(self, tmp_path):
        import api.system as sys_mod
        from api.system import _load_ota_state

        original = sys_mod.OTA_STATE_FILE
        sys_mod.OTA_STATE_FILE = str(tmp_path / "ota_state_fresh.json")
        try:
            state = _load_ota_state()
            assert state["status"] == "idle"
            assert state["running"] is False
        finally:
            sys_mod.OTA_STATE_FILE = original

    def test_load_ota_state_running_flag_derived(self, tmp_path):
        """running must be derived from status == 'running'."""
        import api.system as sys_mod
        from api.system import _load_ota_state

        ota_file = tmp_path / "ota_state.json"
        ota_file.write_text(json.dumps({"status": "running", "mode": "app"}))

        original = sys_mod.OTA_STATE_FILE
        sys_mod.OTA_STATE_FILE = str(ota_file)
        try:
            state = _load_ota_state()
            assert state["running"] is True
            assert state["status"] == "running"
        finally:
            sys_mod.OTA_STATE_FILE = original

    def test_load_ota_state_backfills_missing_keys(self, tmp_path):
        """Schema migration: old state file without new fields gets them backfilled."""
        import api.system as sys_mod
        from api.system import _load_ota_state

        ota_file = tmp_path / "ota_state_old.json"
        # Old format without progress_percent / description / last_error
        ota_file.write_text(json.dumps({
            "status": "done",
            "mode": "app",
            "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T00:01:00",
            "error": None,
        }))

        original = sys_mod.OTA_STATE_FILE
        sys_mod.OTA_STATE_FILE = str(ota_file)
        try:
            state = _load_ota_state()
            assert "progress_percent" in state
            assert "description" in state
            assert "last_error" in state
            assert state["running"] is False
        finally:
            sys_mod.OTA_STATE_FILE = original

    def test_ota_status_endpoint_returns_200(self, system_client):
        rv = system_client.get("/api/system/ota/status")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "status" in data
        assert "running" in data

    def test_ota_status_has_all_fields(self, system_client):
        rv = system_client.get("/api/system/ota/status")
        data = rv.get_json()
        for key in ("running", "status", "mode", "progress_percent", "description",
                    "error", "last_error"):
            assert key in data, f"Campo OTA mancante: {key}"

    def test_ota_log_returns_200(self, system_client):
        rv = system_client.get("/api/system/ota/log")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "log" in data

    def test_ota_start_invalid_mode_returns_400(self, system_client):
        rv = system_client.post(
            "/api/system/ota/start",
            json={"mode": "unknown_mode"},
            content_type="application/json",
        )
        assert rv.status_code == 400

    def test_ota_start_valid_mode_accepted(self, system_client):
        """Valid mode should be accepted (409 if already running is also ok)."""
        with patch("api.system._run_ota"):
            rv = system_client.post(
                "/api/system/ota/start",
                json={"mode": "app"},
                content_type="application/json",
            )
        assert rv.status_code in (200, 409)


# ─── B) Backup name sanitization / path traversal ────────────────────────────

class TestBackupSecurity:

    def test_backup_delete_path_traversal_returns_404(self, system_client, tmp_path):
        """Backup names with path traversal must be rejected (404 — not found)."""
        rv = system_client.delete("/api/system/backups/..%2F..%2Fetc%2Fpasswd")
        assert rv.status_code == 404

    def test_backup_delete_unknown_name_returns_404(self, system_client):
        rv = system_client.delete("/api/system/backups/nonexistent_backup_name")
        assert rv.status_code == 404

    def test_backups_list_returns_200(self, system_client):
        rv = system_client.get("/api/system/backups")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "backups" in data
        assert isinstance(data["backups"], list)

    def test_rollback_missing_name_returns_400(self, system_client):
        rv = system_client.post(
            "/api/system/rollback",
            json={},
            content_type="application/json",
        )
        assert rv.status_code == 400

    def test_rollback_unknown_backup_returns_404(self, system_client):
        rv = system_client.post(
            "/api/system/rollback",
            json={"backup_name": "nonexistent_backup_xyz"},
            content_type="application/json",
        )
        assert rv.status_code == 404

    def test_rollback_path_traversal_rejected(self, system_client):
        rv = system_client.post(
            "/api/system/rollback",
            json={"backup_name": "../../../etc"},
            content_type="application/json",
        )
        assert rv.status_code == 404


# ─── C) Power / system action validation ─────────────────────────────────────

class TestPowerActions:

    def test_system_standby_status_endpoint(self, system_client):
        rv = system_client.get("/api/system/standby")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "in_standby" in data
        assert isinstance(data["in_standby"], bool)

    def test_system_reboot_calls_run_cmd(self, system_client):
        with patch("api.system.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            rv = system_client.post(
                "/api/system",
                json={"azione": "reboot"},
                content_type="application/json",
            )
        assert rv.status_code == 200
        mock_cmd.assert_called()

    def test_system_shutdown_calls_run_cmd(self, system_client):
        with patch("api.system.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            rv = system_client.post(
                "/api/system",
                json={"azione": "shutdown"},
                content_type="application/json",
            )
        assert rv.status_code == 200
        mock_cmd.assert_called()

    def test_system_standby_calls_perform_standby(self, system_client):
        with patch("api.system.perform_standby") as mock_standby:
            rv = system_client.post(
                "/api/system",
                json={"azione": "standby"},
                content_type="application/json",
            )
        assert rv.status_code == 200
        mock_standby.assert_called_once()

    def test_system_empty_action_returns_ok(self, system_client):
        rv = system_client.post(
            "/api/system",
            json={},
            content_type="application/json",
        )
        assert rv.status_code == 200


# ─── D) Standby state logic ───────────────────────────────────────────────────

class TestStandbyLogic:

    def test_is_in_standby_initial_false(self):
        """By default standby should be False at startup."""
        import core.hardware as hw
        hw._in_standby = False
        assert hw.is_in_standby() is False

    def test_perform_standby_sets_flag(self):
        """perform_standby() must set _in_standby to True."""
        import core.hardware as hw
        hw._in_standby = False
        with patch("core.hardware.run_cmd"), \
             patch("core.hardware.amp_off"), \
             patch("core.hardware.eventlet") as mock_ev:
            mock_ev.sleep = MagicMock()
            hw.perform_standby()
        assert hw._in_standby is True

    def test_wake_from_standby_clears_flag(self):
        """wake_from_standby() must set _in_standby to False."""
        import core.hardware as hw
        hw._in_standby = True
        with patch("core.hardware.run_cmd"), \
             patch("core.hardware.amp_on"):
            hw.wake_from_standby()
        assert hw._in_standby is False

    def test_alarm_worker_wakes_from_standby(self):
        """_alarm_worker calls wake_from_standby when standby is active."""
        import core.hardware as hw
        hw._in_standby = True

        wake_called = []

        def _mock_wake():
            wake_called.append(True)
            hw._in_standby = False

        from unittest.mock import patch as _patch
        from datetime import datetime as _dt

        fixed_now = _dt(2026, 1, 5, 0, 0, 0)  # Monday (weekday=0)

        sleep_calls = {"n": 0}

        def _mock_sleep(*args):
            sleep_calls["n"] += 1
            if sleep_calls["n"] > 1:
                raise StopIteration

        with _patch("core.hardware.is_in_standby", side_effect=[True, False]), \
             _patch("core.hardware.wake_from_standby", side_effect=_mock_wake), \
             _patch("core.hardware.eventlet") as mock_ev, \
             _patch("core.hardware.alarms_list", [
                 {"enabled": True, "hour": 0, "minute": 0, "days": list(range(7)), "target": "test.mp3"}
             ]):
            # First sleep passes (loop iteration), second stops the loop
            mock_ev.sleep = MagicMock(side_effect=_mock_sleep)
            try:
                with _patch("core.hardware.datetime") as mock_dt:
                    mock_dt.now.return_value = fixed_now
                    hw._alarm_worker()
            except StopIteration:
                pass

        assert len(wake_called) > 0, "wake_from_standby should have been called"


# ─── E) Network POST /scan alias ─────────────────────────────────────────────

class TestNetworkScanPost:

    def test_post_scan_returns_200(self, network_client):
        with patch("api.network.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "HomeWifi:WPA2:80\nOtherNet:WPA:60", "")
            rv = network_client.post("/api/network/scan")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "networks" in data
        assert isinstance(data["networks"], list)

    def test_get_scan_still_works(self, network_client):
        with patch("api.network.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            rv = network_client.get("/api/network/scan")
        assert rv.status_code == 200


# ─── F) Bluetooth /unblock and /pair ─────────────────────────────────────────

class TestBluetoothNewRoutes:

    def test_bluetooth_unblock_ok(self, network_client):
        with patch("api.network.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            rv = network_client.post("/api/bluetooth/unblock")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data.get("status") == "ok"

    def test_bluetooth_unblock_partial_failure(self, network_client):
        """If rfkill or bluetoothctl fails, returns partial status (not 500)."""
        call_count = {"n": 0}

        def _cmd(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (1, "", "rfkill error")
            return (0, "", "")

        with patch("api.network.run_cmd", side_effect=_cmd):
            rv = network_client.post("/api/bluetooth/unblock")
        assert rv.status_code == 200
        data = rv.get_json()
        assert data.get("status") == "partial"

    def test_bluetooth_pair_missing_mac_returns_400(self, network_client):
        rv = network_client.post(
            "/api/bluetooth/pair",
            json={},
            content_type="application/json",
        )
        assert rv.status_code == 400

    def test_bluetooth_pair_success(self, network_client):
        with patch("api.network.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            rv = network_client.post(
                "/api/bluetooth/pair",
                json={"mac": "AA:BB:CC:DD:EE:FF"},
                content_type="application/json",
            )
        assert rv.status_code == 200
        data = rv.get_json()
        assert data.get("status") == "ok"
        assert data.get("mac") == "AA:BB:CC:DD:EE:FF"

    def test_bluetooth_pair_failure_returns_500(self, network_client):
        with patch("api.network.run_cmd") as mock_cmd:
            mock_cmd.return_value = (1, "", "pairing failed")
            rv = network_client.post(
                "/api/bluetooth/pair",
                json={"mac": "AA:BB:CC:DD:EE:FF"},
                content_type="application/json",
            )
        assert rv.status_code == 500


# ─── G) Diagnostics enriched summary ─────────────────────────────────────────

class TestDiagSummaryEnriched:

    def test_summary_returns_200(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        assert rv.status_code == 200

    def test_summary_has_api_version(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "api_version" in data
        assert isinstance(data["api_version"], str)
        assert len(data["api_version"]) > 0

    def test_summary_has_ota_fields(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "ota_status" in data
        assert "ota_running" in data
        assert isinstance(data["ota_running"], bool)

    def test_summary_has_backup_count(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "backup_count" in data
        assert isinstance(data["backup_count"], int)

    def test_summary_has_standby(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "in_standby" in data
        assert isinstance(data["in_standby"], bool)

    def test_summary_has_alarm_count(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "alarm_count" in data

    def test_summary_has_player_mode(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        data = rv.get_json()
        assert "player_mode" in data

    def test_summary_ok_is_bool(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        assert isinstance(rv.get_json()["ok"], bool)

    def test_summary_warnings_is_list(self, diag_client):
        rv = diag_client.get("/api/diag/summary")
        assert isinstance(rv.get_json()["warnings"], list)
