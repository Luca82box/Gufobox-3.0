# 🦉 GufoBox 3.0

Smart speaker educativo per bambini basato su Raspberry Pi.

---

## Prerequisiti

- **Raspberry Pi** 3B+ / 4 con Raspberry Pi OS (64-bit consigliato)
- Python 3.9+
- Node.js 18+ e npm
- MPV media player: `sudo apt install mpv`
- NetworkManager: `sudo apt install network-manager`
- BlueZ (Bluetooth): solitamente già installato su Raspberry Pi OS

---

## Installazione su Raspberry Pi (installazione rapida)

Per una installazione completa su Raspberry Pi OS, usa lo script automatico:

```bash
# Clona il repository
git clone https://github.com/Luca82box/Gufobox-3.0.git
cd Gufobox-3.0

# Esegui lo script di installazione (richiede sudo)
sudo bash scripts/install-raspberry.sh
```

Lo script installa automaticamente:
- Pacchetti di sistema (ffmpeg, mpv, nodejs, gpio, i2c, spidev, ...)
- Virtualenv Python e tutte le dipendenze (`requirements.txt` + `requirements-hw.txt`)
- Build del frontend Vue
- Servizio systemd `gufobox` (abilitato all'avvio)

Dopo l'installazione:
```bash
# Lo script crea automaticamente .env da .env.example.
# DEVI configurare i valori segnaposto prima di avviare GufoBox:
nano .env
# Imposta almeno:
#   OPENAI_API_KEY=sk-...        (necessaria per Story Studio e chat AI)
#   GUFOBOX_SECRET_KEY=...       (chiave segreta Flask — cambia il valore di default!)

# Avvia il servizio
sudo systemctl start gufobox
sudo systemctl status gufobox

# Controlla i log
journalctl -u gufobox -f
```

Accedi all'interfaccia su: `http://gufobox.local:5000` (o `http://<IP>:5000`)

### Opzioni avanzate dello script

```bash
sudo bash scripts/install-raspberry.sh --help

# Salta l'installazione apt (utile per aggiornamenti veloci del solo codice):
sudo bash scripts/install-raspberry.sh --skip-apt

# Non creare il servizio systemd:
sudo bash scripts/install-raspberry.sh --skip-service
```

> **Guida completa Raspberry Pi:** vedi [`docs/raspberry-setup.md`](docs/raspberry-setup.md)
> per istruzioni dettagliate su installazione, Piper TTS offline, manifest pacchetti e troubleshooting.

---

## Installazione manuale (sviluppo / passo passo)

```bash
# 1. Clona il repository
git clone https://github.com/carlanluca-alt/Gufobox-3.0.git
cd Gufobox-3.0

# 2. Crea e attiva un ambiente virtuale Python
python3 -m venv venv
source venv/bin/activate

# 3. Installa le dipendenze Python
pip install -r requirements.txt

# 4. Copia il file di configurazione ambiente e personalizzalo
cp .env.example .env
nano .env
```

---

## Installazione Frontend

```bash
cd frontend
npm install
```

---

## Avvio in sviluppo

### Backend (Flask + SocketIO)

```bash
# Dalla root del progetto, con virtualenv attivo
python main.py
```

Il server sarà disponibile su `http://localhost:5000`.

### Frontend (Vite + Vue 3)

```bash
cd frontend
npm run dev
```

Il dev server sarà disponibile su `http://localhost:5174`.

---

## Variabili d'ambiente

Copia `.env.example` in `.env` e configura:

| Variabile | Descrizione |
|-----------|-------------|
| `OPENAI_API_KEY` | Chiave API OpenAI (opzionale, per le funzioni AI) |
| `GUFOBOX_SECRET_KEY` | Chiave segreta Flask per le sessioni |
| `GUFOBOX_ADMIN_PIN` | PIN di accesso al pannello admin |
| `GUFOBOX_COOKIE_SECURE` | `1` per HTTPS, `0` per HTTP (sviluppo) |
| `GUFOBOX_COOKIE_SAMESITE` | Policy cookie (`Lax` di default) |

Vedi `.env.example` per la lista completa.

---

## Risoluzione problemi (Troubleshooting)

### Story Studio: "Errore durante la generazione"

Se Story Studio mostra un errore durante la generazione della storia:

1. **Chiave API OpenAI non configurata** — il messaggio tipico è
   *"Client OpenAI non inizializzato"* o *"Errore di autenticazione OpenAI"*.
   - Vai su **Pannello Admin → Impostazioni AI** e inserisci la tua `OPENAI_API_KEY`.
   - In alternativa, aggiungila al file `.env`: `OPENAI_API_KEY=sk-...`
   - Riavvia il servizio: `sudo systemctl restart gufobox`

2. **Quota OpenAI esaurita o rate limit** — riprova tra qualche minuto o verifica
   il tuo piano su [platform.openai.com](https://platform.openai.com).

3. Per ulteriori dettagli tecnici, controlla i log del server:
   ```bash
   journalctl -u gufobox -n 50 --no-pager
   ```

### Voce offline Piper non funziona

Piper richiede il **binario eseguibile** e le **librerie condivise** (`libonnxruntime.so.*`,
`libpiper_phonemize.so.*`) presenti nella stessa directory.

**Installazione automatica (consigliata su RPi con internet):**
1. Pannello Admin → Voce offline → clic su **Scarica binario automaticamente**

**Installazione manuale (senza internet):**
1. Scarica `piper_linux_aarch64.tar.gz` da
   [github.com/rhasspy/piper/releases](https://github.com/rhasspy/piper/releases)
   su un altro PC
2. Estrai tutto il contenuto dell'archivio
3. Carica tutti i file estratti (binario `piper`, `.so.*`, cartella `espeak-ng-data/`)
   tramite Pannello Admin → Voce offline → **Carica file Piper** (target: `bin`)
4. Carica i file voce `.onnx` e `.onnx.json` (target: `voices`)

**Nota voci:** ogni voce richiede **entrambi** i file `.onnx` e `.onnx.json`.
Se uno dei due è mancante, lo stato API riporta il messaggio esatto di cosa manca.

**Diagnostica:**
- `GET /api/tts/offline/status` — mostra `piper_available`, `voices_status` (completezza
  per ogni voce), e `voice_diagnosi` con il messaggio preciso in italiano se la voce
  configurata è incompleta
- Verifica che il binario sia ARM64: `file data/piper_bin/piper`

### GPIO / pulsanti non funzionano

Se vedi `Unable to load any default pin factory!` nei log:
```bash
# Installa lgpio (il driver preferito su Raspberry Pi OS bookworm)
sudo apt install -y python3-lgpio
pip install lgpio
```

Se usi il virtualenv del progetto:
```bash
source venv/bin/activate
pip install lgpio RPi.GPIO
```

---



Alcune funzioni richiedono hardware fisico e permessi specifici:

- **GPIO driver (lgpio)**: richiesto da `gpiozero` per accesso ai pin GPIO
  ```bash
  sudo apt install -y python3-lgpio
  ```
- **I2C (smbus2)**: richiesto da `hw/battery.py` per il fuel gauge MAX17048
  ```bash
  pip install smbus2
  ```
  oppure installa le dipendenze hardware complete con:
  ```bash
  pip install -r requirements-hw.txt || true
  ```
- **GPIO** (pulsanti, LED, amplificatore): assicurati che l'utente sia nel gruppo `gpio`
  ```bash
  sudo usermod -aG gpio $USER
  ```
- **SPI** (RFID, LED NeoPixel): abilitare SPI da `raspi-config` → Interface Options → SPI
- **I2C** (batteria): abilitare I2C da `raspi-config` → Interface Options → I2C
- **Bluetooth**: l'utente deve essere nel gruppo `bluetooth`
  ```bash
  sudo usermod -aG bluetooth $USER
  ```
- **Volume ALSA**: `amixer` deve essere disponibile (`sudo apt install alsa-utils`)

> **Nota:** All'interno di un container Docker le funzioni hardware GPIO/SPI/I2C non saranno disponibili. Il backend può comunque girare in container per test/sviluppo senza hardware fisico.

---

## Ottimizzazione Raspberry Pi: tmpfs per log e upload temporanei

Per ridurre le scritture sulla microSD e migliorare le prestazioni, si consiglia di montare in RAM (tmpfs) le directory dei log e degli upload temporanei.

### Configurazione automatica

Esegui lo script incluso nel repository (richiede sudo):

```bash
bash scripts/setup-raspberry-tmpfs.sh
```

Lo script crea le directory, fa un backup di `/etc/fstab` e aggiunge i mount tmpfs rilevando automaticamente uid/gid dell'utente `gufobox`.

### Configurazione manuale

```bash
# Verifica uid/gid dell'utente gufobox
id gufobox

# Crea le directory (se non esistono già)
mkdir -p /home/gufobox/data/logs
mkdir -p /home/gufobox/data/tmp_uploads

# Backup di fstab
sudo cp /etc/fstab /etc/fstab.backup

# Aggiungi i mount tmpfs (sostituisci uid/gid con i valori reali)
echo 'tmpfs /home/gufobox/data/logs        tmpfs defaults,noatime,nosuid,size=32m,uid=1000,gid=1000,mode=0755 0 0' | sudo tee -a /etc/fstab
echo 'tmpfs /home/gufobox/data/tmp_uploads tmpfs defaults,noatime,nosuid,size=64m,uid=1000,gid=1000,mode=0755 0 0' | sudo tee -a /etc/fstab

# Monta senza riavviare
sudo mount -a
```

> **Note:**
> - I dati in tmpfs vengono persi al riavvio: adatto per log e file temporanei, non per dati persistenti.
> - Adatta `size=32m` / `size=64m` in base alla RAM disponibile.

---

## Struttura del progetto

```
Gufobox-3.0/
├── main.py              # Entry point del server Flask
├── config.py            # Configurazione globale
├── requirements.txt     # Dipendenze Python
├── .env.example         # Template variabili d'ambiente
├── Dockerfile           # Immagine Docker per il backend
├── core/
│   ├── state.py         # EventBus + gestione stato globale
│   ├── database.py      # SQLite (statistiche + smart resume)
│   ├── media.py         # Motore audio (MPV + IPC socket)
│   ├── hardware.py      # Worker hardware (sleep timer)
│   ├── discovery.py     # mDNS (Zeroconf)
│   ├── extensions.py    # Flask-SocketIO
│   └── utils.py         # Logging e helper
├── api/
│   ├── ai.py            # OpenAI chat, TTS, giochi educativi
│   ├── files.py         # File manager
│   ├── media.py         # Player API (play, stop, next, prev, volume)
│   ├── network.py       # Wi-Fi e Bluetooth
│   ├── settings.py      # Impostazioni admin
│   ├── system.py        # Reboot / standby
│   └── voice.py         # Registrazione vocale
├── hw/
│   ├── amp.py           # Amplificatore GPIO
│   ├── battery.py       # Monitoraggio batteria I2C
│   ├── buttons.py       # Pulsanti fisici GPIO
│   ├── led.py           # LED NeoPixel SPI
│   └── rfid.py          # Lettore RFID SPI
└── frontend/
    ├── index.html        # Entry point Vite
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.js
        ├── router.js
        ├── App.vue
        ├── views/        # Pagine (Home, Admin e sotto-pannelli)
        ├── components/   # TopBar, PinModal
        └── composables/  # useApi, useAuth, useMedia, useAi, useFileManager
```

---

## Modalità Bluetooth

GufoBox supporta due modalità d'uso Bluetooth distinte:

### Modalità Sink — GufoBox come sorgente audio verso device esterni

In questa modalità GufoBox si connette a **casse o cuffie Bluetooth esterne** e invia l'audio verso di esse.

- Usa `/api/bluetooth/scan` per trovare i device vicini
- Usa `/api/bluetooth/connect` con il MAC del device per collegarsi
- Il profilo A2DP source viene utilizzato automaticamente da BlueZ

### Modalità Source / Speaker — GufoBox come cassa Bluetooth

In questa modalità GufoBox si presenta come uno **speaker Bluetooth** a cui un telefono, tablet o altra sorgente può collegarsi per inviare audio.

- Usa `POST /api/bluetooth/source-mode` con `{"enabled": true}` per rendere GufoBox visibile e accoppiabile
- Il dispositivo esterno (telefono/tablet) troverà GufoBox nella lista speaker Bluetooth e potrà collegarsi
- Usa `POST /api/bluetooth/source-mode` con `{"enabled": false}` per disabilitare la visibilità

> **Nota pratica:** la modalità speaker dipende anche dalla configurazione audio del sistema Raspberry Pi.
> Per ricevere davvero audio via Bluetooth è necessario avere uno di questi stack installato e configurato:
> `BlueALSA`, `PulseAudio` (con modulo Bluetooth) o `PipeWire` (con WirePlumber).
> L'API espone le rotte necessarie e gestisce la parte BlueZ (visibilità/accoppiamento),
> ma la riproduzione audio reale dipende dallo stack audio del sistema.

---

## Tech Stack

- **Backend**: Python, Flask, Flask-SocketIO, Eventlet
- **Frontend**: Vue 3, Composition API, Vite
- **Hardware**: Raspberry Pi, GPIO, SPI, I2C
- **AI**: OpenAI API (chat + TTS)
- **Media**: MPV (con controllo IPC socket)
