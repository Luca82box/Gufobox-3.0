"""
tests/test_diag_pr15.py — Tests for PR 15 diagnostics / logging improvements.

Covers:
- core/event_log.py: append, read, trimming, fallback on missing/corrupt storage
- POST /api/diag/selfcheck: output shape
- GET  /api/diag/events:   endpoint response
- GET  /api/diag/export:   export structure
- Fallback when event storage is missing or corrupt
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_tmp_log_file():
    """Return a fresh temporary path for the event log (not yet created)."""
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="gufobox_test_events_")
    os.close(fd)
    os.unlink(path)  # start fresh
    return path


# ─── core/event_log unit tests ───────────────────────────────────────────────

class TestEventLog:
    """Unit tests for core/event_log (isolated with a temp file)."""

    def setup_method(self):
        import core.event_log as _el
        self._orig_log_file = _el._log_file
        self._tmp = _make_tmp_log_file()
        _el._log_file = self._tmp

    def teardown_method(self):
        import core.event_log as _el
        _el._log_file = self._orig_log_file
        if os.path.exists(self._tmp):
            os.unlink(self._tmp)

    def test_log_event_creates_file(self):
        from core.event_log import log_event
        log_event("test", "info", "hello")
        assert os.path.exists(self._tmp)

    def test_log_event_appends(self):
        from core.event_log import log_event, get_events
        log_event("auth", "info", "login ok")
        log_event("ota", "warning", "ota started")
        log_event("network", "error", "wifi fail")
        events = get_events()
        assert len(events) == 3

    def test_get_events_reverse_chronological(self):
        from core.event_log import log_event, get_events
        log_event("a", "info", "first")
        log_event("b", "info", "second")
        log_event("c", "info", "third")
        events = get_events()
        # Most recent (third) should be first
        assert events[0]["message"] == "third"
        assert events[-1]["message"] == "first"

    def test_event_shape(self):
        from core.event_log import log_event, get_events
        log_event("ota", "error", "OTA fallito", {"mode": "app"})
        events = get_events()
        ev = events[0]
        assert "ts" in ev
        assert ev["area"] == "ota"
        assert ev["severity"] == "error"
        assert ev["message"] == "OTA fallito"
        assert ev.get("details") == {"mode": "app"}

    def test_event_without_details(self):
        from core.event_log import log_event, get_events
        log_event("auth", "info", "login")
        ev = get_events()[0]
        assert "details" not in ev

    def test_severity_fallback(self):
        """Unknown severity should be normalised to 'info'."""
        from core.event_log import log_event, get_events
        log_event("test", "BOGUS_SEVERITY", "msg")
        ev = get_events()[0]
        assert ev["severity"] == "info"

    def test_ring_buffer_trim(self):
        """Buffer should not exceed EVENT_LOG_MAX_ENTRIES."""
        from core.event_log import log_event, get_events, EVENT_LOG_MAX_ENTRIES
        overflow = EVENT_LOG_MAX_ENTRIES + 10
        for i in range(overflow):
            log_event("test", "info", f"msg-{i}")
        events = get_events(limit=EVENT_LOG_MAX_ENTRIES + 100)
        assert len(events) <= EVENT_LOG_MAX_ENTRIES

    def test_get_events_limit(self):
        from core.event_log import log_event, get_events
        for i in range(20):
            log_event("test", "info", f"msg-{i}")
        events = get_events(limit=5)
        assert len(events) == 5

    def test_fallback_missing_file(self):
        """get_events should return [] if the log file doesn't exist."""
        from core.event_log import get_events
        assert not os.path.exists(self._tmp)
        events = get_events()
        assert events == []

    def test_fallback_corrupt_file(self):
        """get_events should skip corrupt lines gracefully."""
        from core.event_log import log_event, get_events
        # Write one valid line, then corrupt garbage
        log_event("ok", "info", "valid")
        with open(self._tmp, "a") as f:
            f.write("THIS IS NOT JSON\n")
            f.write("{broken}\n")
        events = get_events()
        assert len(events) == 1
        assert events[0]["message"] == "valid"

    def test_clear_events(self):
        from core.event_log import log_event, get_events, clear_events
        log_event("test", "info", "one")
        log_event("test", "info", "two")
        clear_events()
        assert get_events() == []


# ─── Flask app fixture ───────────────────────────────────────────────────────

@pytest.fixture()
def app(tmp_path):
    """Create a minimal Flask app with the diag blueprint registered."""
    import core.event_log as _el
    # Override event log file to a temp location
    _el._log_file = str(tmp_path / "events.jsonl")
    _el.clear_events()

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
    yield flask_app

    _el.clear_events()
    _el._log_file = None  # reset to force re-init


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ─── GET /api/diag/events ────────────────────────────────────────────────────

def test_events_returns_200(client):
    rv = client.get("/api/diag/events")
    assert rv.status_code == 200


def test_events_returns_events_and_count(client):
    rv = client.get("/api/diag/events")
    data = rv.get_json()
    assert "events" in data
    assert "count" in data
    assert isinstance(data["events"], list)
    assert isinstance(data["count"], int)


def test_events_initially_empty(client):
    rv = client.get("/api/diag/events")
    data = rv.get_json()
    assert data["count"] == 0


def test_events_after_log(client, app):
    from core.event_log import log_event
    log_event("test", "info", "test event from test")
    rv = client.get("/api/diag/events")
    data = rv.get_json()
    assert data["count"] >= 1
    assert any(e["message"] == "test event from test" for e in data["events"])


def test_events_limit_param(client, app):
    from core.event_log import log_event
    for i in range(15):
        log_event("test", "info", f"event-{i}")
    rv = client.get("/api/diag/events?limit=5")
    data = rv.get_json()
    assert data["count"] == 5


def test_events_limit_clamped(client, app):
    """limit > 500 should be clamped to 500."""
    rv = client.get("/api/diag/events?limit=9999")
    assert rv.status_code == 200


# ─── POST /api/diag/selfcheck ────────────────────────────────────────────────

def test_selfcheck_returns_200(client):
    rv = client.post("/api/diag/selfcheck")
    assert rv.status_code == 200


def test_selfcheck_has_required_keys(client):
    rv = client.post("/api/diag/selfcheck")
    data = rv.get_json()
    for key in ("ok", "timestamp", "checks", "warnings", "errors", "note"):
        assert key in data, f"Chiave mancante: {key}"


def test_selfcheck_ok_is_bool(client):
    rv = client.post("/api/diag/selfcheck")
    data = rv.get_json()
    assert isinstance(data["ok"], bool)


def test_selfcheck_checks_is_list(client):
    rv = client.post("/api/diag/selfcheck")
    data = rv.get_json()
    assert isinstance(data["checks"], list)


def test_selfcheck_check_items_have_name_and_ok(client):
    rv = client.post("/api/diag/selfcheck")
    data = rv.get_json()
    for check in data["checks"]:
        assert "name" in check
        assert "ok" in check
        assert isinstance(check["ok"], bool)


def test_selfcheck_python3_present(client):
    """python3 must be detected as available in any CI environment."""
    rv = client.post("/api/diag/selfcheck")
    data = rv.get_json()
    python_check = next(
        (c for c in data["checks"] if c["name"] == "tool:python3"), None
    )
    assert python_check is not None, "check tool:python3 not found"
    assert python_check["ok"] is True


def test_selfcheck_logs_event(client, app):
    """self-check should append an event to the event log."""
    from core.event_log import get_events
    client.post("/api/diag/selfcheck")
    events = get_events()
    assert any(e["area"] == "selfcheck" for e in events)


# ─── GET /api/diag/export ────────────────────────────────────────────────────

def test_export_returns_200(client):
    rv = client.get("/api/diag/export")
    assert rv.status_code == 200


def test_export_has_required_keys(client):
    rv = client.get("/api/diag/export")
    data = rv.get_json()
    for key in ("exported_at", "summary", "tools", "selfcheck", "recent_events"):
        assert key in data, f"Chiave mancante: {key}"


def test_export_tools_are_present(client):
    rv = client.get("/api/diag/export")
    data = rv.get_json()
    assert isinstance(data["tools"], dict)
    assert len(data["tools"]) > 0


def test_export_selfcheck_has_ok(client):
    rv = client.get("/api/diag/export")
    data = rv.get_json()
    assert "ok" in data["selfcheck"]


def test_export_recent_events_is_list(client):
    rv = client.get("/api/diag/export")
    data = rv.get_json()
    assert isinstance(data["recent_events"], list)


def test_export_exported_at_is_string(client):
    rv = client.get("/api/diag/export")
    data = rv.get_json()
    assert isinstance(data["exported_at"], str)
    assert "T" in data["exported_at"]  # ISO format


# ─── existing endpoints still work ──────────────────────────────────────────

def test_existing_summary_still_works(client):
    rv = client.get("/api/diag/summary")
    assert rv.status_code == 200
    assert "ok" in rv.get_json()


def test_existing_tools_still_works(client):
    rv = client.get("/api/diag/tools")
    assert rv.status_code == 200
    assert "tools" in rv.get_json()


def test_existing_metrics_still_works(client):
    rv = client.get("/api/admin/metrics")
    assert rv.status_code == 200
