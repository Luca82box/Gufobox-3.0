"""
core/connectivity.py — Utility per il check di connettività internet e OpenAI.

Fornisce:
  has_internet(timeout=3) -> bool   — True se la rete è raggiungibile
  has_openai()            -> bool   — True se la chiave OpenAI è configurata E internet è up

I risultati vengono cachati per 30 secondi per evitare check ripetuti ad ogni trigger RFID.
"""

import socket
import time

from core.utils import log

# =========================================================
# Cache interna (semplicissima, thread-safe su GIL)
# =========================================================
_CACHE_TTL = 30  # secondi

_internet_cache: dict = {"result": None, "ts": 0.0}
_openai_cache: dict   = {"result": None, "ts": 0.0}


# =========================================================
# PUBLIC API
# =========================================================

def has_internet(timeout: int = 3) -> bool:
    """
    Tenta una connessione TCP verso 1.1.1.1:53 (DNS Cloudflare).
    Ritorna True se raggiungibile, False altrimenti.
    Il risultato è cachato per _CACHE_TTL secondi.
    """
    now = time.monotonic()
    if _internet_cache["result"] is not None and (now - _internet_cache["ts"]) < _CACHE_TTL:
        return _internet_cache["result"]

    result = _check_internet(timeout)
    _internet_cache["result"] = result
    _internet_cache["ts"] = now
    return result


def has_openai() -> bool:
    """
    Ritorna True se la chiave OPENAI_API_KEY è configurata E internet è disponibile.
    Il risultato è cachato per _CACHE_TTL secondi.
    """
    now = time.monotonic()
    if _openai_cache["result"] is not None and (now - _openai_cache["ts"]) < _CACHE_TTL:
        return _openai_cache["result"]

    from config import OPENAI_API_KEY
    key_ok = bool(OPENAI_API_KEY and OPENAI_API_KEY.strip())
    result = key_ok and has_internet()
    _openai_cache["result"] = result
    _openai_cache["ts"] = now
    return result


def invalidate_cache() -> None:
    """Invalida immediatamente la cache (utile nei test o dopo cambio rete)."""
    _internet_cache["result"] = None
    _internet_cache["ts"] = 0.0
    _openai_cache["result"] = None
    _openai_cache["ts"] = 0.0


# =========================================================
# INTERNAL
# =========================================================

def _check_internet(timeout: int) -> bool:
    """Esegue il check TCP effettivo verso 1.1.1.1:53."""
    try:
        sock = socket.create_connection(("1.1.1.1", 53), timeout=timeout)
        sock.close()
        return True
    except OSError:
        log("Check connettività: nessuna rete disponibile", "info")
        return False
