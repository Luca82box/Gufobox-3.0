"""
tests/test_diag.py — Smoke tests per api/diag.py

Copre:
- GET /api/admin/metrics  — risponde con 200 e campi attesi
- GET /api/diag/summary   — risponde con 200 e campi attesi
- GET /api/diag/tools     — risponde con 200 e campi attesi
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def app():
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
def client(app):
    with app.test_client() as c:
        yield c


# ─── /api/admin/metrics ──────────────────────────────────────────────────────

def test_metrics_returns_200(client):
    rv = client.get("/api/admin/metrics")
    assert rv.status_code == 200


def test_metrics_has_expected_keys(client):
    rv = client.get("/api/admin/metrics")
    data = rv.get_json()
    for key in ("cpu_temp_celsius", "cpu_load", "ram", "disk", "battery", "uptime_seconds"):
        assert key in data, f"Chiave mancante: {key}"


def test_metrics_ram_has_expected_sub_keys(client):
    rv = client.get("/api/admin/metrics")
    ram = rv.get_json()["ram"]
    for key in ("total_mb", "available_mb", "used_mb", "percent"):
        assert key in ram


def test_metrics_disk_has_expected_sub_keys(client):
    rv = client.get("/api/admin/metrics")
    disk = rv.get_json()["disk"]
    for key in ("total_gb", "used_gb", "free_gb", "percent"):
        assert key in disk


def test_metrics_cpu_load_has_expected_sub_keys(client):
    rv = client.get("/api/admin/metrics")
    load = rv.get_json()["cpu_load"]
    for key in ("load_1", "load_5", "load_15"):
        assert key in load


def test_metrics_disk_total_is_positive_or_none(client):
    rv = client.get("/api/admin/metrics")
    total = rv.get_json()["disk"]["total_gb"]
    # In ambiente Linux (CI) il disco è disponibile
    if total is not None:
        assert total > 0


# ─── /api/diag/summary ───────────────────────────────────────────────────────

def test_summary_returns_200(client):
    rv = client.get("/api/diag/summary")
    assert rv.status_code == 200


def test_summary_has_expected_keys(client):
    rv = client.get("/api/diag/summary")
    data = rv.get_json()
    for key in ("ok", "warnings", "cpu_temp_celsius", "ram_percent", "disk_percent", "uptime_seconds"):
        assert key in data


def test_summary_ok_is_bool(client):
    rv = client.get("/api/diag/summary")
    assert isinstance(rv.get_json()["ok"], bool)


def test_summary_warnings_is_list(client):
    rv = client.get("/api/diag/summary")
    assert isinstance(rv.get_json()["warnings"], list)


# ─── /api/diag/tools ─────────────────────────────────────────────────────────

def test_tools_returns_200(client):
    rv = client.get("/api/diag/tools")
    assert rv.status_code == 200


def test_tools_has_expected_keys(client):
    rv = client.get("/api/diag/tools")
    data = rv.get_json()
    assert "tools" in data
    assert "all_critical_ok" in data


def test_tools_values_are_bool(client):
    rv = client.get("/api/diag/tools")
    tools = rv.get_json()["tools"]
    for name, val in tools.items():
        assert isinstance(val, bool), f"Tool '{name}' non è bool"


def test_tools_python3_detected(client):
    """python3 deve essere disponibile in qualsiasi ambiente CI."""
    rv = client.get("/api/diag/tools")
    tools = rv.get_json()["tools"]
    # python3 deve essere trovato in ambienti Linux standard
    assert tools.get("python3") is True


# ─── helper functions unit tests ─────────────────────────────────────────────

def test_cpu_temperature_returns_float_or_none():
    from api.diag import _cpu_temperature
    result = _cpu_temperature()
    assert result is None or isinstance(result, float)


def test_ram_info_returns_dict():
    from api.diag import _ram_info
    result = _ram_info()
    assert isinstance(result, dict)
    assert "total_mb" in result


def test_disk_info_returns_dict():
    from api.diag import _disk_info
    result = _disk_info()
    assert isinstance(result, dict)
    assert "total_gb" in result


def test_uptime_seconds_positive_or_none():
    from api.diag import _uptime_seconds
    result = _uptime_seconds()
    assert result is None or result >= 0


def test_check_tool_python3():
    from api.diag import _check_tool
    # python3 deve essere disponibile
    assert _check_tool("python3") is True or _check_tool("python") is True
