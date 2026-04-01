"""
conftest.py — Configurazione globale per i test pytest.

Fa il mock di os.makedirs a livello di sessione, in modo che config.py
non tenti di creare /home/gufobox o altre directory sistema durante i test.
"""
import os
import sys

# Aggiunge la root del progetto al path prima di qualsiasi import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch os.makedirs per i test: tollera i permessi negati invece di crashare
_orig_makedirs = os.makedirs

def _safe_makedirs(path, mode=0o777, exist_ok=False):
    try:
        _orig_makedirs(path, mode=mode, exist_ok=exist_ok)
    except (PermissionError, FileNotFoundError):
        pass  # In ambiente test ignoriamo i permessi negati su directory sistema

os.makedirs = _safe_makedirs
