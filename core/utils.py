import os
import json
import logging
import subprocess
from copy import deepcopy
from logging.handlers import RotatingFileHandler
from config import LOG_DIR

# =========================================================
# LOGGING STRUTTURATO
# =========================================================
logger = logging.getLogger("gufobox")
logger.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
logger.addHandler(_console_handler)

log_file = os.path.join(LOG_DIR, "gufobox.log")
_file_handler = RotatingFileHandler(log_file, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
logger.addHandler(_file_handler)

def log(msg, level="info"):
    getattr(logger, level, logger.info)(msg)

# =========================================================
# ESECUZIONE COMANDI E SICUREZZA FILE
# =========================================================
def run_cmd(cmd, timeout=20, cwd=None):
    """Esegue un comando sul terminale del Raspberry in modo sicuro"""
    try:
        cp = subprocess.run(cmd, cwd=cwd, timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return cp.returncode, (cp.stdout or "").strip(), (cp.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)

def secure_open_read(path, allowed_roots):
    """TOCTOU Security: Previene race condition sui symlink usando i file descriptors"""
    try:
        path_abs = os.path.realpath(path)
        if not any(path_abs.startswith(os.path.realpath(r) + os.sep) for r in allowed_roots):
            raise ValueError("Access Denied")
        # Apre con O_NOFOLLOW per impedire il parsing di link simbolici creati all'ultimo ms
        fd = os.open(path_abs, os.O_RDONLY | os.O_NOFOLLOW)
        return os.fdopen(fd, "rb")
    except OSError:
        raise ValueError("Symlink attack detected or file not found")

# =========================================================
# GESTIONE I18N (Lingue)
# =========================================================
LANG_STRINGS = {
    "it": {
        "ok_standby": "Standby attivato", "ok_reboot": "Riavvio avviato"
    },
    "en": {
        "ok_standby": "Standby activated", "ok_reboot": "Reboot started"
    },
    "es": {
        "ok_standby": "Modo de espera activado", "ok_reboot": "Reinicio iniciado"
    },
    "de": {
        "ok_standby": "Standby aktiviert", "ok_reboot": "Neustart gestartet"
    }
}

_current_lang = "it"

def set_lang(lang_code):
    global _current_lang
    if lang_code in LANG_STRINGS:
        _current_lang = lang_code

def t(key):
    return LANG_STRINGS.get(_current_lang, LANG_STRINGS["it"]).get(key, key)

