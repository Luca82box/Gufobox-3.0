"""
conftest.py — Configurazione globale per i test pytest.

Fa il mock di os.makedirs a livello di sessione, in modo che config.py
non tenti di creare /home/gufobox o altre directory sistema durante i test.
"""
# eventlet.monkey_patch() deve essere chiamato prima di qualsiasi import che
# dipenda da eventlet (es. core.state, core.media). Va eseguito qui, all'inizio
# del conftest, per garantire che i green thread siano correttamente inizializzati
# in tutti i test.
import eventlet
eventlet.monkey_patch()

import os
import sys
import pytest
from unittest.mock import MagicMock

# Aggiunge la root del progetto al path prima di qualsiasi import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock hardware-specific modules that are not available in CI/test environments:
# gpiozero (hw/amp.py, hw/buttons.py), smbus2 (hw/battery.py)
for _hw_mod in ("gpiozero", "smbus2"):
    if _hw_mod not in sys.modules:
        sys.modules[_hw_mod] = MagicMock()

# Patch os.makedirs per i test: tollera i permessi negati invece di crashare.
# Il patch viene applicato a livello globale (non tramite fixture) perché config.py
# chiama os.makedirs al top-level, cioè al momento dell'import — prima che qualsiasi
# fixture possa essere attivata. L'originale viene ripristinato dalla fixture
# autouse di sessione qui sotto.
_orig_makedirs = os.makedirs

def _safe_makedirs(path, mode=0o777, exist_ok=False):
    try:
        _orig_makedirs(path, mode=mode, exist_ok=exist_ok)
    except (PermissionError, FileNotFoundError):
        pass  # In ambiente test ignoriamo i permessi negati su directory sistema

os.makedirs = _safe_makedirs


@pytest.fixture(scope="session", autouse=True)
def _restore_makedirs():
    """Ripristina os.makedirs originale al termine della sessione di test."""
    yield
    os.makedirs = _orig_makedirs
