# 🦉 GufoBox 2.0

Smart speaker educativo per bambini basato su Raspberry Pi.

## Struttura del progetto

- `main.py` — Entry point del server Flask
- `config.py` — Configurazione globale
- `core/` — Moduli core (state, database, extensions, media engine, hardware manager, utilities)
- `api/` — Blueprint API REST (ai, files, media, network, settings, system, voice)
- `hw/` — Driver hardware fisici (amplificatore, batteria, pulsanti, LED, RFID)
- `frontend/src/` — Interfaccia Vue.js 3
  - `views/` — Pagine principali
  - `components/` — Componenti riutilizzabili
  - `composables/` — Composables Vue (useApi, useAuth, useMedia, ecc.)

## Tech Stack
- **Backend**: Python, Flask, Flask-SocketIO, Eventlet
- **Frontend**: Vue 3, Composition API
- **Hardware**: Raspberry Pi, GPIO, SPI, I2C
- **AI**: OpenAI API
