"""
tests/test_auth.py — Test per api/auth.py

Copre:
- login con PIN corretto
- login con PIN errato
- blocco dopo troppi tentativi
- sessione: /api/auth/session
- logout: /api/auth/logout
- require_admin decorator
"""

import os
import sys
import json
import time
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── helpers di setup ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_auth_state():
    """Resetta lo stato auth tra un test e l'altro."""
    from core.state import state
    state.pop("auth", None)
    yield
    state.pop("auth", None)


@pytest.fixture()
def app():
    """Crea una Flask app minimale con solo il blueprint auth montato."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.auth import auth_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret-key"
    flask_app.config["TESTING"] = True
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    CORS(flask_app, supports_credentials=True)
    flask_app.register_blueprint(auth_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ─── test login ──────────────────────────────────────────────────────────────

def test_login_correct_pin_returns_token(client):
    """Login con PIN corretto deve ritornare admin_token."""
    rv = client.post("/api/admin/login", json={"pin": "1234"})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["status"] == "ok"
    assert "admin_token" in data
    assert len(data["admin_token"]) > 10


def test_login_wrong_pin_returns_401(client):
    """Login con PIN errato deve ritornare 401."""
    rv = client.post("/api/admin/login", json={"pin": "9999"})
    assert rv.status_code == 401
    data = rv.get_json()
    assert "error" in data


def test_login_missing_pin_returns_401(client):
    """Login senza pin deve ritornare 401."""
    rv = client.post("/api/admin/login", json={})
    assert rv.status_code == 401


def test_login_lockout_after_max_fails(client):
    """Dopo 5 tentativi errati l'account deve essere bloccato (429)."""
    for _ in range(5):
        client.post("/api/admin/login", json={"pin": "0000"})
    rv = client.post("/api/admin/login", json={"pin": "0000"})
    assert rv.status_code == 429
    data = rv.get_json()
    assert "retry_in" in data


def test_login_success_resets_fail_counter(client):
    """Dopo un login riuscito il contatore fails deve essere 0."""
    from core.state import state
    # Inserisci alcuni fails
    client.post("/api/admin/login", json={"pin": "0000"})
    client.post("/api/admin/login", json={"pin": "0000"})
    # Login corretto
    rv = client.post("/api/admin/login", json={"pin": "1234"})
    assert rv.status_code == 200
    assert state["auth"]["fails"] == 0


# ─── test session ────────────────────────────────────────────────────────────

def test_session_unauthenticated_returns_false(client):
    """Senza login, /api/auth/session deve ritornare authenticated=False."""
    rv = client.get("/api/auth/session")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["authenticated"] is False


def test_session_after_login_returns_true(client):
    """Dopo il login, /api/auth/session deve ritornare authenticated=True."""
    client.post("/api/admin/login", json={"pin": "1234"})
    rv = client.get("/api/auth/session")
    data = rv.get_json()
    assert data["authenticated"] is True


def test_session_with_bearer_token(client):
    """Sessione valida con Bearer token deve ritornare token_authenticated=True."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    rv = client.get("/api/auth/session", headers={"Authorization": f"Bearer {token}"})
    data = rv.get_json()
    assert data["token_authenticated"] is True
    assert data["authenticated"] is True


def test_session_with_wrong_bearer_token(client):
    """Bearer token errato deve ritornare token_authenticated=False."""
    rv = client.get("/api/auth/session", headers={"Authorization": "Bearer wrongtoken"})
    data = rv.get_json()
    assert data["token_authenticated"] is False


# ─── test logout ─────────────────────────────────────────────────────────────

def test_logout_clears_session(client):
    """Logout deve invalidare la sessione."""
    client.post("/api/admin/login", json={"pin": "1234"})
    rv_before = client.get("/api/auth/session")
    assert rv_before.get_json()["authenticated"] is True

    client.post("/api/auth/logout")
    rv_after = client.get("/api/auth/session")
    assert rv_after.get_json()["session_authenticated"] is False


def test_logout_revokes_token(client):
    """Logout deve revocare l'admin_token."""
    from core.state import state
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    client.post("/api/auth/logout")

    assert state["auth"]["admin_token"] is None
    # Bearer con il vecchio token non dovrebbe più funzionare
    rv = client.get("/api/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert rv.get_json()["token_authenticated"] is False


# ─── test require_admin decorator ────────────────────────────────────────────

def test_require_admin_blocks_unauthenticated(app, client):
    """require_admin deve bloccare richieste non autenticate con 401."""
    from api.auth import require_admin
    from flask import Blueprint, jsonify

    test_bp = Blueprint("testbp", __name__)

    @test_bp.route("/protected-test")
    @require_admin
    def _protected():
        return jsonify({"ok": True})

    app.register_blueprint(test_bp, url_prefix="/api")

    rv = client.get("/api/protected-test")
    assert rv.status_code == 401


def test_require_admin_allows_authenticated(app, client):
    """require_admin deve permettere richieste con sessione admin valida."""
    from api.auth import require_admin
    from flask import Blueprint, jsonify

    test_bp2 = Blueprint("testbp2", __name__)

    @test_bp2.route("/protected-test2")
    @require_admin
    def _protected2():
        return jsonify({"ok": True})

    app.register_blueprint(test_bp2, url_prefix="/api")

    client.post("/api/admin/login", json={"pin": "1234"})
    rv = client.get("/api/protected-test2")
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True
