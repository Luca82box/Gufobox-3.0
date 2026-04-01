import time
import requests
import eventlet
from core.utils import log

try:
    from mfrc522 import SimpleMFRC522
except ImportError:
    SimpleMFRC522 = None

API_BASE = "http://127.0.0.1:5000/api"

def _rfid_worker():
    if not SimpleMFRC522:
        log("Libreria mfrc522 non trovata. Driver RFID inattivo.", "error")
        return

    # Inizializza il lettore (usa di default i pin SPI corretti: CS GPIO8, SCK GPIO11, MOSI GPIO10, MISO GPIO9)
    reader = SimpleMFRC522()
    last_uid = None
    last_read_time = 0

    log("Lettore RFID (RC522) in ascolto via SPI...", "info")

    while True:
        try:
            # reader.read() è bloccante, ma legge velocemente. 
            # Potremmo usare read_no_block() se serve più reattività.
            id, text = reader.read()
            uid_str = str(id)

            now = time.time()
            
            # Debounce: evitiamo di sparare l'avvio 100 volte se la statuina resta appoggiata
            if uid_str != last_uid or (now - last_read_time) > 3:
                log(f"Statuina FISICA rilevata! UID: {uid_str}", "info")
                
                try:
                    # Inviamo il codice letto alle nostre API
                    res = requests.post(
                        f"{API_BASE}/rfid/trigger", 
                        json={"rfid_code": uid_str}, 
                        timeout=3
                    )
                    
                    if res.status_code == 200:
                        last_uid = uid_str
                        last_read_time = now
                except Exception as e:
                    log(f"Errore di comunicazione API dall'RFID: {e}", "warning")

        except Exception as e:
            log(f"Errore lettura RC522: {e}", "warning")
        
        # Pausa per non impallare la CPU (il thread eventlet)
        eventlet.sleep(0.5)

def init_rfid():
    # Facciamo partire il thread in background
    eventlet.spawn(_rfid_worker)

