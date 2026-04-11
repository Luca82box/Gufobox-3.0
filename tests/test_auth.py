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


# ─── test pin/change ─────────────────────────────────────────────────────────

def test_pin_change_success(client):
    """Cambio PIN riuscito con autenticazione valida."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    rv = client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "5678"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["status"] == "ok"


def test_pin_change_requires_auth(client):
    """Cambio PIN deve essere rifiutato senza autenticazione (401)."""
    rv = client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "5678"},
    )
    assert rv.status_code == 401


def test_pin_change_wrong_current_pin(client):
    """Cambio PIN deve essere rifiutato se il PIN corrente è errato."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    rv = client.post(
        "/api/auth/pin/change",
        json={"current_pin": "0000", "new_pin": "5678"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rv.status_code == 401


def test_pin_change_invalid_new_pin_non_numeric(client):
    """Cambio PIN deve essere rifiutato se il nuovo PIN non è numerico."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    rv = client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "abcd"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rv.status_code == 400
    assert "error" in rv.get_json()


def test_pin_change_invalid_new_pin_too_short(client):
    """Cambio PIN deve essere rifiutato se il nuovo PIN è troppo corto."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    rv = client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "12"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rv.status_code == 400


def test_pin_change_invalid_new_pin_too_long(client):
    """Cambio PIN deve essere rifiutato se il nuovo PIN è troppo lungo."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    rv = client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "123456789"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rv.status_code == 400


def test_pin_change_old_pin_no_longer_works(client):
    """Dopo il cambio PIN il vecchio PIN non deve più funzionare."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "5678"},
        headers={"Authorization": f"Bearer {token}"},
    )

    rv = client.post("/api/admin/login", json={"pin": "1234"})
    assert rv.status_code == 401


def test_pin_change_new_pin_works_after_change(client):
    """Dopo il cambio PIN il nuovo PIN deve funzionare."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "5678"},
        headers={"Authorization": f"Bearer {token}"},
    )

    rv = client.post("/api/admin/login", json={"pin": "5678"})
    assert rv.status_code == 200
    assert rv.get_json()["status"] == "ok"


def test_pin_change_invalidates_token(client):
    """Dopo il cambio PIN il vecchio token deve essere invalidato."""
    login_rv = client.post("/api/admin/login", json={"pin": "1234"})
    token = login_rv.get_json()["admin_token"]

    client.post(
        "/api/auth/pin/change",
        json={"current_pin": "1234", "new_pin": "5678"},
        headers={"Authorization": f"Bearer {token}"},
    )

    rv = client.get("/api/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert rv.get_json()["token_authenticated"] is False


# ─── test input malformati ────────────────────────────────────────────────────

def test_login_invalid_json_returns_401(client):
    """Login con body non JSON deve ritornare 401 (pin vuoto non valido)."""
    rv = client.post(
        "/api/admin/login",
        data="not-json",
        content_type="text/plain",
    )
    assert rv.status_code == 401


def test_login_empty_body_returns_401(client):
    """Login con body vuoto deve ritornare 401."""
    rv = client.post("/api/admin/login", json={})
    assert rv.status_code == 401


def test_login_pin_format_non_numeric(client):
    """Login con PIN non numerico deve ritornare 401."""
    rv = client.post("/api/admin/login", json={"pin": "abcd"})
    assert rv.status_code == 401


def test_login_pin_format_too_short(client):
    """Login con PIN troppo corto deve ritornare 401."""
    rv = client.post("/api/admin/login", json={"pin": "12"})
    assert rv.status_code == 401


def test_login_pin_format_too_long(client):
    """Login con PIN troppo lungo deve ritornare 401."""
    rv = client.post("/api/admin/login", json={"pin": "123456789"})
    assert rv.status_code == 401


def test_login_pin_very_long_string(client):
    """Login con stringa molto lunga deve essere rifiutato senza crash."""
    rv = client.post("/api/admin/login", json={"pin": "1" * 10000})
    assert rv.status_code == 401


# ─── test persistenza locked_until ───────────────────────────────────────────

def test_locked_until_persists_in_state(client):
    """locked_until deve essere salvato nello stato dopo il blocco."""
    from core.state import state

    for _ in range(5):
        client.post("/api/admin/login", json={"pin": "0000"})

    auth = state.get("auth", {})
    assert auth.get("locked_until", 0) > time.time(), \
        "locked_until deve essere un timestamp futuro dopo il blocco"


def test_locked_until_restored_blocks_login(client):
    """Se locked_until è nel futuro nello stato, il login deve essere bloccato."""
    from core.state import state
    from api.auth import init_auth

    # Forza il blocco direttamente nello stato
    state["auth"] = {
        "pin_hash": None,  # sarà reimpostato da init_auth se necessario
        "admin_token": None,
        "fails": 5,
        "locked_until": int(time.time()) + 120,
    }

    rv = client.post("/api/admin/login", json={"pin": "1234"})
    assert rv.status_code == 429
    data = rv.get_json()
    assert "retry_in" in data
    assert data["retry_in"] > 0


# ─── test robustezza init_auth con stato nullo/malformato ────────────────────

def test_init_auth_with_null_state(client):
    """init_auth deve gestire state['auth'] = None senza crash e ripristinare il default."""
    from core.state import state
    from api.auth import init_auth

    state["auth"] = None
    init_auth()

    assert isinstance(state["auth"], dict), "auth deve essere un dict dopo init_auth"
    assert "pin_hash" in state["auth"]
    assert "admin_token" in state["auth"]
    assert "fails" in state["auth"]
    assert "locked_until" in state["auth"]


def test_init_auth_with_non_dict_state(client):
    """init_auth deve gestire state['auth'] = stringa/intero senza crash."""
    from core.state import state
    from api.auth import init_auth

    for bad_value in [42, "malformed", [], True]:
        state["auth"] = bad_value
        init_auth()
        assert isinstance(state["auth"], dict), \
            f"auth deve essere dict dopo init_auth con valore {bad_value!r}"


def test_login_after_null_auth_state(client):
    """Il login deve funzionare dopo che lo stato auth era None."""
    from core.state import state

    state["auth"] = None
    rv = client.post("/api/admin/login", json={"pin": "1234"})
    assert rv.status_code == 200
    assert rv.get_json()["status"] == "ok"


def test_auth_state_helper_reinitializes_null(client):
    """_auth_state() deve reinizializzare se state['auth'] è None."""
    from core.state import state
    from api.auth import _auth_state

    state["auth"] = None
    auth = _auth_state()
    assert isinstance(auth, dict)
    assert "pin_hash" in auth


def test_init_auth_missing_keys_are_added(client):
    """init_auth deve aggiungere le chiavi mancanti a un dict auth parziale."""
    from core.state import state
    from api.auth import init_auth

    import hashlib
    from config import SECRET_KEY, ADMIN_DEFAULT_PIN
    pin_hash = hashlib.sha256(SECRET_KEY.encode() + ADMIN_DEFAULT_PIN.encode()).hexdigest()
    state["auth"] = {"pin_hash": pin_hash, "admin_token": None}

    init_auth()

    assert "fails" in state["auth"]
    assert "locked_until" in state["auth"]
