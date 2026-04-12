# IMPORTANTE (eventlet): usare SEMPRE eventlet.sleep() nei loop di questo
# worker — mai time.sleep(). time.time() per i timestamp è OK (non bloccante).

import time
import eventlet
from core.utils import log, is_shutdown_requested

try:
    from mfrc522 import SimpleMFRC522
except ImportError:
    SimpleMFRC522 = None

API_BASE = "http://127.0.0.1:5000/api"


def _trigger_rfid_direct(uid_str):
    """Chiama direttamente la logica Python invece di un roundtrip HTTP locale."""
    try:
        from api.rfid import handle_rfid_trigger
        return handle_rfid_trigger(uid_str)
    except ImportError:
        return False
    except Exception as e:
        log(f"Chiamata diretta RFID fallita: {e}", "warning")
        return False


def _trigger_rfid_http(uid_str):
    """Fallback: chiama l'API via HTTP (richiede che Flask sia già avviato)."""
    try:
        import requests
        res = requests.post(
            f"{API_BASE}/rfid/trigger",
            json={"rfid_code": uid_str},
            timeout=3
        )
        return res.status_code == 200
    except Exception as e:
        log(f"Errore di comunicazione API dall'RFID (HTTP fallback): {e}", "warning")
        return False


def _rfid_worker():
    if not SimpleMFRC522:
        log("Libreria mfrc522 non trovata. Driver RFID inattivo.", "error")
        return

    # Inizializza il lettore (usa di default i pin SPI corretti: CS GPIO8, SCK GPIO11, MOSI GPIO10, MISO GPIO9)
    reader = SimpleMFRC522()
    last_uid = None
    last_read_time = 0

    log("Lettore RFID (RC522) in ascolto via SPI...", "info")

    while not is_shutdown_requested():
        try:
            # read_no_block() ritorna (None, None) quando non c'è nessuna scheda,
            # evitando di bloccare il thread eventlet indefinitamente come farebbe read().
            id, text = reader.read_no_block()
            if id is None:
                eventlet.sleep(0.1)
                continue

            uid_str = str(id)

            now = time.time()

            # Debounce: evitiamo di sparare l'avvio 100 volte se la statuina resta appoggiata
            if uid_str != last_uid or (now - last_read_time) > 3:
                log(f"Statuina FISICA rilevata! UID: {uid_str}", "info")

                # Prima prova la chiamata Python diretta, poi fallback HTTP
                success = False
                try:
                    success = _trigger_rfid_direct(uid_str)
                except Exception as e:
                    log(f"Chiamata diretta RFID fallita, provo HTTP: {e}", "warning")
                    success = _trigger_rfid_http(uid_str)

                if success:
                    last_uid = uid_str
                    last_read_time = now

        except Exception as e:
            log(f"Errore lettura RC522: {e}", "warning")

        # Pausa cooperativa per cedere il controllo all'hub eventlet
        eventlet.sleep(0.1)

    log("Worker RFID terminato (shutdown richiesto).", "info")

def init_rfid():
    # Facciamo partire il thread in background
    eventlet.spawn(_rfid_worker)

