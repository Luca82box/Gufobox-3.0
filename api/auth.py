"""
api/auth.py — Admin authentication endpoints.

Implements:
  POST /api/admin/login   — login with PIN, returns admin_token
  GET  /api/auth/session  — check current session / token
  POST /api/auth/logout   — clear session and token
"""

import hashlib
import hmac
import re
import secrets
import time

from flask import Blueprint, request, jsonify, session

from core.state import state, bus, save_json_direct
from core.utils import log
from core.event_log import log_event
from config import STATE_FILE, SECRET_KEY

auth_bp = Blueprint("auth", __name__)

# ─── tunables ────────────────────────────────────────────────────────────────
_MAX_FAILS = 5          # tentativi errati prima del blocco
_LOCKOUT_SECS = 60      # secondi di blocco
_SESSION_TIMEOUT = 3600 # secondi di validità sessione Flask
_DEFAULT_PIN = "1234"
# ─────────────────────────────────────────────────────────────────────────────


def _default_auth_state():
    return {
        "pin_hash": _hash_pin(_DEFAULT_PIN),
        "admin_token": None,
        "fails": 0,
        "locked_until": 0,
    }


def _hash_pin(pin: str) -> str:
    """SHA-256 del PIN con salt basato su SECRET_KEY."""
    salt = SECRET_KEY.encode()
    return hashlib.sha256(salt + pin.encode()).hexdigest()


def _auth_state() -> dict:
    """Ritorna il sotto-dict di autenticazione dallo stato globale (lo crea se assente)."""
    if "auth" not in state:
        state["auth"] = _default_auth_state()
        bus.mark_dirty("state")
    return state["auth"]


def init_auth():
    """Garantisce che lo stato di autenticazione sia inizializzato all'avvio."""
    if "auth" not in state:
        state["auth"] = _default_auth_state()
        bus.mark_dirty("state")
    auth = state["auth"]
    # Garantisci che tutte le chiavi necessarie esistano
    defaults = _default_auth_state()
    for key, default_val in defaults.items():
        if key not in auth:
            auth[key] = default_val
    # Se il pin_hash non è un hex valido di 64 caratteri, reimpostalo al default
    pin_hash = auth.get("pin_hash", "")
    if not (isinstance(pin_hash, str) and re.fullmatch(r"[0-9a-f]{64}", pin_hash)):
        auth["pin_hash"] = _hash_pin(_DEFAULT_PIN)
        bus.mark_dirty("state")


# Inizializza subito all'import
init_auth()


def _is_locked() -> bool:
    return _auth_state().get("locked_until", 0) > time.time()


def _remaining_lockout() -> int:
    remaining = int(_auth_state().get("locked_until", 0) - time.time())
    return max(0, remaining)


def _token_valid(token: str) -> bool:
    stored = _auth_state().get("admin_token")
    if not stored or not token:
        return False
    return hmac.compare_digest(stored, token)


def _is_session_authenticated() -> bool:
    ts = session.get("admin_ts", 0)
    return session.get("admin_authenticated") is True and (time.time() - ts) < _SESSION_TIMEOUT


# ─── endpoints ───────────────────────────────────────────────────────────────

@auth_bp.route("/admin/login", methods=["POST"])
def api_admin_login():
    """
    Login admin con PIN.
    Payload: {"pin": "1234"}
    Risposta successo: {"status": "ok", "admin_token": "<token>"}
    Risposta errore:   {"error": "..."} con 401 / 429
    """
    if _is_locked():
        return jsonify({"error": "Troppi tentativi. Riprova più tardi.", "retry_in": _remaining_lockout()}), 429

    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", "")).strip()

    auth = _auth_state()
    expected_hash = auth.get("pin_hash") or _hash_pin(_DEFAULT_PIN)

    if hmac.compare_digest(_hash_pin(pin), expected_hash):
        # Login riuscito
        auth["fails"] = 0
        auth["locked_until"] = 0

        # Genera / rinnova token
        token = secrets.token_hex(32)
        auth["admin_token"] = token

        # Sessione Flask
        session["admin_authenticated"] = True
        session["admin_ts"] = int(time.time())
        session.permanent = True

        bus.mark_dirty("state")
        save_json_direct(STATE_FILE, state)

        log("Login admin riuscito", "info")
        bus.emit_notification("Accesso admin effettuato 🔓", "info")
        log_event("auth", "info", "Login admin riuscito")
        return jsonify({"status": "ok", "admin_token": token})

    else:
        # Login fallito
        auth["fails"] = auth.get("fails", 0) + 1
        if auth["fails"] >= _MAX_FAILS:
            auth["locked_until"] = int(time.time()) + _LOCKOUT_SECS
            log(f"Admin bloccato per {_LOCKOUT_SECS}s dopo {_MAX_FAILS} tentativi", "warning")
            bus.emit_notification("Troppi PIN errati — accesso bloccato ⛔", "warning")
            log_event("auth", "warning", f"Admin bloccato dopo {_MAX_FAILS} tentativi errati")
        else:
            log_event("auth", "warning", "Tentativo login admin fallito (PIN errato)")

        bus.mark_dirty("state")
        save_json_direct(STATE_FILE, state)

        remaining = _remaining_lockout()
        if remaining > 0:
            return jsonify({"error": "Account bloccato.", "retry_in": remaining}), 429
        return jsonify({"error": "PIN errato"}), 401


@auth_bp.route("/auth/session", methods=["GET"])
def api_auth_session():
    """
    Verifica se l'utente ha una sessione admin valida.
    Controlla sia la sessione Flask sia il Bearer token.
    Risposta: {"authenticated": bool, "token_authenticated": bool}
    """
    token_auth = False
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        token_auth = _token_valid(token)

    session_auth = _is_session_authenticated()

    authenticated = session_auth or token_auth
    return jsonify({
        "authenticated": authenticated,
        "session_authenticated": session_auth,
        "token_authenticated": token_auth,
    })


@auth_bp.route("/auth/logout", methods=["POST"])
def api_auth_logout():
    """
    Logout admin: invalida la sessione Flask e revoca il token.
    """
    session.pop("admin_authenticated", None)
    session.pop("admin_ts", None)

    auth = _auth_state()
    auth["admin_token"] = None
    bus.mark_dirty("state")
    save_json_direct(STATE_FILE, state)

    log("Logout admin", "info")
    log_event("auth", "info", "Logout admin")
    return jsonify({"status": "ok"})


@auth_bp.route("/auth/pin/change", methods=["POST"])
def api_auth_pin_change():
    """
    Cambia il PIN admin.
    Richiede autenticazione Bearer token o sessione attiva.
    Payload: {"current_pin": "1234", "new_pin": "5678"}
    """
    # Verifica autenticazione
    token_ok = False
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token_ok = _token_valid(auth_header[7:].strip())
    if not (_is_session_authenticated() or token_ok):
        return jsonify({"error": "Autenticazione richiesta"}), 401

    data = request.get_json(silent=True) or {}
    current_pin = str(data.get("current_pin", "")).strip()
    new_pin = str(data.get("new_pin", "")).strip()

    if not current_pin or not new_pin:
        return jsonify({"error": "current_pin e new_pin richiesti"}), 400

    auth = _auth_state()
    expected_hash = auth.get("pin_hash") or _hash_pin(_DEFAULT_PIN)
    if not hmac.compare_digest(_hash_pin(current_pin), expected_hash):
        return jsonify({"error": "PIN attuale non corretto"}), 401

    if not new_pin.isdigit() or len(new_pin) < 4 or len(new_pin) > 8:
        return jsonify({"error": "Il nuovo PIN deve essere numerico, da 4 a 8 cifre"}), 400

    auth["pin_hash"] = _hash_pin(new_pin)
    auth["admin_token"] = None  # Invalida tutti i token esistenti
    bus.mark_dirty("state")
    save_json_direct(STATE_FILE, state)

    log("PIN admin modificato", "info")
    log_event("auth", "info", "PIN admin modificato con successo")
    return jsonify({"status": "ok", "message": "PIN cambiato. Effettua nuovamente il login."})


# ─── helper riusabile ────────────────────────────────────────────────────────

def require_admin(f):
    """
    Decorator riusabile per proteggere endpoint admin.
    Controlla sessione Flask e/o Bearer token.
    """
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        token_ok = False
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_ok = _token_valid(auth_header[7:].strip())
        if not (_is_session_authenticated() or token_ok):
            return jsonify({"error": "Autenticazione richiesta"}), 401
        return f(*args, **kwargs)
    return wrapper
