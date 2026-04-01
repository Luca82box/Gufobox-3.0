# 🦉 GufoBox 2.0

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

## Installazione Backend

```bash
# 1. Clona il repository
git clone https://github.com/carlanluca-alt/Gufobox-2.0.git
cd Gufobox-2.0

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

## Note Raspberry Pi / Permessi Hardware

Alcune funzioni richiedono hardware fisico e permessi specifici:

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

## Struttura del progetto

```
Gufobox-2.0/
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
