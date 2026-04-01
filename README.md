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

Il dev server sarà disponibile su `http://localhost:5173`.

---

## Variabili d'ambiente

Copia `.env.example` in `.env` e configura:

| Variabile | Descrizione |
|-----------|-------------|
| `OPENAI_API_KEY` | Chiave API OpenAI (opzionale, per le funzioni AI) |
| `SECRET_KEY` | Chiave segreta Flask per le sessioni |
| `ADMIN_PIN` | PIN di accesso al pannello admin |

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

## Tech Stack

- **Backend**: Python, Flask, Flask-SocketIO, Eventlet
- **Frontend**: Vue 3, Composition API, Vite
- **Hardware**: Raspberry Pi, GPIO, SPI, I2C
- **AI**: OpenAI API (chat + TTS)
- **Media**: MPV (con controllo IPC socket)
