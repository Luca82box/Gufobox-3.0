"""
tests/test_ai_pr18.py — PR 18: AI polish.

Covers:
A) DEFAULT_AI_RUNTIME shape: status, last_error, history, legacy booleans
B) _set_ai_state(): canonical status + legacy bool sync + led_runtime sync
C) GET /ai/status: shape, openai_configured, history_length
D) POST /ai/stop: resets to idle
E) POST /ai/listen/start and /ai/listen/stop: transitions
F) POST /ai/clear-history (and alias /ai/clear): clears history, resets to idle
G) POST /ai/chat: no client -> 503 + code field + event logged
H) POST /ai/chat: history trimmed to <= 10, timestamps in entries
I) POST /ai/chat: successful response path (mocked OpenAI)
J) POST /ai/chat: OpenAI exception -> error state + event logged
K) ai_runtime snapshot keys present
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --- fixtures -----------------------------------------------------------------

@pytest.fixture()
def ai_app():
    """Minimal Flask app with ai_bp registered."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.ai import ai_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-ai-secret"
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
def reset_ai_runtime():
    """Reset ai_runtime and led ai_state before each test."""
    from core.state import ai_runtime, led_runtime, DEFAULT_AI_RUNTIME
    from copy import deepcopy
    ai_runtime.clear()
    ai_runtime.update(deepcopy(DEFAULT_AI_RUNTIME))
    led_runtime["ai_state"] = None
    yield


@pytest.fixture()
def tmp_event_log():
    """Redirect event_log to a temp file for the duration of the test."""
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


# --- A) DEFAULT_AI_RUNTIME shape ----------------------------------------------

class TestDefaultAiRuntime:
    def test_has_status_field(self):
        from core.state import DEFAULT_AI_RUNTIME
        assert "status" in DEFAULT_AI_RUNTIME
        assert DEFAULT_AI_RUNTIME["status"] == "idle"

    def test_has_last_error(self):
        from core.state import DEFAULT_AI_RUNTIME
        assert "last_error" in DEFAULT_AI_RUNTIME
        assert DEFAULT_AI_RUNTIME["last_error"] is None

    def test_has_history(self):
        from core.state import DEFAULT_AI_RUNTIME
        assert "history" in DEFAULT_AI_RUNTIME
        assert DEFAULT_AI_RUNTIME["history"] == []

    def test_legacy_booleans_present(self):
        from core.state import DEFAULT_AI_RUNTIME
        assert "is_thinking" in DEFAULT_AI_RUNTIME
        assert "is_speaking" in DEFAULT_AI_RUNTIME
        assert DEFAULT_AI_RUNTIME["is_thinking"] is False
        assert DEFAULT_AI_RUNTIME["is_speaking"] is False


# --- B) _set_ai_state() -------------------------------------------------------

class TestSetAiState:
    def test_thinking_sets_status_and_booleans(self):
        from api.ai import _set_ai_state
        from core.state import ai_runtime
        _set_ai_state("thinking")
        assert ai_runtime["status"] == "thinking"
        assert ai_runtime["is_thinking"] is True
        assert ai_runtime["is_speaking"] is False

    def test_speaking_sets_status_and_booleans(self):
        from api.ai import _set_ai_state
        from core.state import ai_runtime
        _set_ai_state("speaking")
        assert ai_runtime["status"] == "speaking"
        assert ai_runtime["is_speaking"] is True
        assert ai_runtime["is_thinking"] is False

    def test_idle_clears_booleans_and_last_error(self):
        from api.ai import _set_ai_state
        from core.state import ai_runtime
        ai_runtime["last_error"] = "prev error"
        _set_ai_state("idle")
        assert ai_runtime["status"] == "idle"
        assert ai_runtime["is_thinking"] is False
        assert ai_runtime["is_speaking"] is False
        assert ai_runtime["last_error"] is None

    def test_error_sets_last_error(self):
        from api.ai import _set_ai_state
        from core.state import ai_runtime
        _set_ai_state("error", error="Something went wrong")
        assert ai_runtime["status"] == "error"
        assert ai_runtime["last_error"] == "Something went wrong"

    def test_led_runtime_synced_for_thinking(self):
        from api.ai import _set_ai_state
        from core.state import led_runtime
        _set_ai_state("thinking")
        assert led_runtime["ai_state"] == "thinking"

    def test_led_runtime_none_for_idle(self):
        from api.ai import _set_ai_state
        from core.state import led_runtime
        led_runtime["ai_state"] = "speaking"
        _set_ai_state("idle")
        assert led_runtime["ai_state"] is None

    def test_listening_state(self):
        from api.ai import _set_ai_state
        from core.state import ai_runtime, led_runtime
        _set_ai_state("listening")
        assert ai_runtime["status"] == "listening"
        assert led_runtime["ai_state"] == "listening"


# --- C) GET /ai/status --------------------------------------------------------

class TestAiStatusEndpoint:
    def test_status_returns_200(self, client):
        r = client.get("/api/ai/status")
        assert r.status_code == 200

    def test_status_payload_shape(self, client):
        data = json.loads(client.get("/api/ai/status").data)
        assert "status" in data
        assert "last_error" in data
        assert "history_length" in data
        assert "tts_provider" in data
        assert "openai_configured" in data

    def test_status_default_idle(self, client):
        from core.state import ai_runtime
        ai_runtime["status"] = "idle"
        data = json.loads(client.get("/api/ai/status").data)
        assert data["status"] == "idle"

    def test_status_reflects_thinking(self, client):
        from core.state import ai_runtime
        ai_runtime["status"] = "thinking"
        data = json.loads(client.get("/api/ai/status").data)
        assert data["status"] == "thinking"

    def test_history_length_correct(self, client):
        from core.state import ai_runtime
        ai_runtime["history"] = [
            {"role": "user", "content": "hi", "ts": 1},
            {"role": "assistant", "content": "hello", "ts": 2},
        ]
        data = json.loads(client.get("/api/ai/status").data)
        assert data["history_length"] == 2


# --- D) POST /ai/stop ---------------------------------------------------------

class TestAiStopEndpoint:
    def test_stop_returns_ok(self, client):
        r = client.post("/api/ai/stop")
        assert r.status_code == 200
        assert json.loads(r.data)["status"] == "ok"

    def test_stop_resets_to_idle(self, client):
        from core.state import ai_runtime
        ai_runtime["status"] = "thinking"
        ai_runtime["is_thinking"] = True
        client.post("/api/ai/stop")
        assert ai_runtime["status"] == "idle"
        assert ai_runtime["is_thinking"] is False


# --- E) POST /ai/listen/start and /ai/listen/stop ----------------------------

class TestAiListenEndpoints:
    def test_listen_start_sets_listening(self, client):
        from core.state import ai_runtime
        r = client.post("/api/ai/listen/start")
        assert r.status_code == 200
        assert ai_runtime["status"] == "listening"

    def test_listen_stop_reverts_to_idle(self, client):
        from core.state import ai_runtime
        ai_runtime["status"] = "listening"
        r = client.post("/api/ai/listen/stop")
        assert r.status_code == 200
        assert ai_runtime["status"] == "idle"

    def test_listen_stop_noop_when_not_listening(self, client):
        from core.state import ai_runtime
        ai_runtime["status"] = "speaking"
        client.post("/api/ai/listen/stop")
        assert ai_runtime["status"] == "speaking"


# --- F) POST /ai/clear-history (and alias /ai/clear) -------------------------

class TestAiClearHistory:
    def test_clear_history_returns_ok(self, client):
        r = client.post("/api/ai/clear-history")
        assert r.status_code == 200
        assert json.loads(r.data)["status"] == "ok"

    def test_clear_history_empties_history(self, client):
        from core.state import ai_runtime
        ai_runtime["history"] = [{"role": "user", "content": "hi", "ts": 1}]
        client.post("/api/ai/clear-history")
        assert ai_runtime["history"] == []

    def test_clear_history_resets_status(self, client):
        from core.state import ai_runtime
        ai_runtime["status"] = "error"
        client.post("/api/ai/clear-history")
        assert ai_runtime["status"] == "idle"

    def test_clear_alias_works(self, client):
        from core.state import ai_runtime
        ai_runtime["history"] = [{"role": "user", "content": "hi", "ts": 1}]
        r = client.post("/api/ai/clear")
        assert r.status_code == 200
        assert ai_runtime["history"] == []


# --- G) POST /ai/chat: no client -> 503 --------------------------------------

class TestAiChatNoClient:
    def test_chat_without_openai_returns_fallback_reply(self, client):
        """When OpenAI is not configured, the endpoint returns 200 with a friendly fallback reply."""
        with patch("api.ai.get_openai_client", return_value=None):
            r = client.post(
                "/api/ai/chat",
                data=json.dumps({"text": "ciao"}),
                content_type="application/json",
            )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data.get("status") == "ok"
        assert data.get("offline") is True
        assert isinstance(data.get("reply"), str) and len(data["reply"]) > 0

    def test_chat_without_openai_no_503_error_code(self, client):
        """When OpenAI is not configured, the response must NOT contain openai_not_configured error."""
        with patch("api.ai.get_openai_client", return_value=None):
            r = client.post(
                "/api/ai/chat",
                data=json.dumps({"text": "ciao"}),
                content_type="application/json",
            )
        data = json.loads(r.data)
        assert data.get("code") != "openai_not_configured"

    def test_chat_empty_text_returns_400(self, client):
        r = client.post(
            "/api/ai/chat",
            data=json.dumps({"text": "   "}),
            content_type="application/json",
        )
        assert r.status_code == 400


# --- H) POST /ai/chat: history trimmed, timestamps ---------------------------

class TestAiChatHistory:
    def _mock_openai_response(self, reply_text="Risposta di test"):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = reply_text
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        return mock_client

    def test_history_trimmed_to_10(self, client):
        from core.state import ai_runtime
        ai_runtime["history"] = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg{i}", "ts": i}
            for i in range(10)
        ]
        mock_oa = self._mock_openai_response()
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            with patch("api.ai.ai_settings", {
                "tts_provider": "browser", "system_prompt": "test",
                "temperature": 0.7, "model": "gpt-3.5-turbo"
            }):
                client.post(
                    "/api/ai/chat",
                    data=json.dumps({"text": "nuovo messaggio"}),
                    content_type="application/json",
                )
        assert len(ai_runtime["history"]) <= 10

    def test_history_entries_have_ts(self, client):
        from core.state import ai_runtime
        mock_oa = self._mock_openai_response("risposta")
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            with patch("api.ai.ai_settings", {
                "tts_provider": "browser", "system_prompt": "test",
                "temperature": 0.7, "model": "gpt-3.5-turbo"
            }):
                client.post(
                    "/api/ai/chat",
                    data=json.dumps({"text": "ciao"}),
                    content_type="application/json",
                )
        for entry in ai_runtime["history"]:
            assert "ts" in entry, f"Entry missing ts: {entry}"


# --- I) POST /ai/chat: successful response ------------------------------------

class TestAiChatSuccess:
    def test_chat_success_returns_reply(self, client):
        mock_oa = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Ciao bambino!"
        mock_oa.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            with patch("api.ai.ai_settings", {
                "tts_provider": "browser", "system_prompt": "test",
                "temperature": 0.7, "model": "gpt-3.5-turbo"
            }):
                r = client.post(
                    "/api/ai/chat",
                    data=json.dumps({"text": "ciao"}),
                    content_type="application/json",
                )
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["reply"] == "Ciao bambino!"
        assert data["status"] == "ok"

    def test_chat_success_status_idle_browser_tts(self, client):
        from core.state import ai_runtime
        mock_oa = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "risposta"
        mock_oa.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            with patch("api.ai.ai_settings", {
                "tts_provider": "browser", "system_prompt": "test",
                "temperature": 0.7, "model": "gpt-3.5-turbo"
            }):
                client.post(
                    "/api/ai/chat",
                    data=json.dumps({"text": "ciao"}),
                    content_type="application/json",
                )
        assert ai_runtime["status"] == "idle"


# --- J) POST /ai/chat: OpenAI exception -> error state + event logged ---------

class TestAiChatError:
    def test_openai_exception_returns_500(self, client, tmp_event_log):
        mock_oa = MagicMock()
        mock_oa.chat.completions.create.side_effect = RuntimeError("API error")
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            with patch("api.ai.ai_settings", {
                "tts_provider": "browser", "system_prompt": "test",
                "temperature": 0.7, "model": "gpt-3.5-turbo"
            }):
                r = client.post(
                    "/api/ai/chat",
                    data=json.dumps({"text": "ciao"}),
                    content_type="application/json",
                )
        assert r.status_code == 500

    def test_openai_exception_sets_error_state(self, client, tmp_event_log):
        from core.state import ai_runtime
        mock_oa = MagicMock()
        mock_oa.chat.completions.create.side_effect = RuntimeError("fail")
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            with patch("api.ai.ai_settings", {
                "tts_provider": "browser", "system_prompt": "test",
                "temperature": 0.7, "model": "gpt-3.5-turbo"
            }):
                client.post(
                    "/api/ai/chat",
                    data=json.dumps({"text": "ciao"}),
                    content_type="application/json",
                )
        assert ai_runtime["status"] == "error"
        assert ai_runtime["last_error"] is not None

    def test_openai_exception_logs_event(self, client, tmp_event_log):
        from core.event_log import get_events
        mock_oa = MagicMock()
        mock_oa.chat.completions.create.side_effect = RuntimeError("fail")
        with patch("api.ai.get_openai_client", return_value=mock_oa):
            with patch("api.ai.ai_settings", {
                "tts_provider": "browser", "system_prompt": "test",
                "temperature": 0.7, "model": "gpt-3.5-turbo"
            }):
                client.post(
                    "/api/ai/chat",
                    data=json.dumps({"text": "ciao"}),
                    content_type="application/json",
                )
        events = get_events(limit=10)
        ai_errors = [e for e in events if e.get("area") == "ai" and e.get("severity") == "error"]
        assert len(ai_errors) > 0

    def test_no_openai_logs_event(self, client, tmp_event_log):
        from core.event_log import get_events
        with patch("api.ai.get_openai_client", return_value=None):
            client.post(
                "/api/ai/chat",
                data=json.dumps({"text": "ciao"}),
                content_type="application/json",
            )
        events = get_events(limit=10)
        # Now logs a warning (fallback reply sent) instead of an error
        ai_events = [e for e in events if e.get("area") == "ai" and e.get("severity") in ("error", "warning")]
        assert len(ai_events) > 0


# --- K) ai_runtime snapshot includes expected keys ---------------------------

class TestAiRuntimeSnapshot:
    def test_runtime_snapshot_has_status(self):
        from core.state import ai_runtime
        assert "status" in ai_runtime

    def test_runtime_snapshot_has_last_error(self):
        from core.state import ai_runtime
        assert "last_error" in ai_runtime

    def test_runtime_snapshot_legacy_keys_present(self):
        from core.state import ai_runtime
        assert "is_thinking" in ai_runtime
        assert "is_speaking" in ai_runtime
