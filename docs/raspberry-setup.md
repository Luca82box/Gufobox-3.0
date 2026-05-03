# 🦉 GufoBox 3.0 — Guida di installazione su Raspberry Pi

Questa guida descrive la procedura completa per installare GufoBox 3.0 su un
Raspberry Pi partendo da zero, inclusa la configurazione di Piper TTS offline.

---

## Prerequisiti hardware e OS

| Componente | Requisito minimo |
|---|---|
| Raspberry Pi | 3B+ / 4 / 5 (64-bit consigliato) |
| OS | Raspberry Pi OS Bookworm Lite o Desktop (64-bit) |
| Storage | MicroSD da 16 GB (32 GB consigliato) |
| Connessione | Internet attiva durante l'installazione |

---

## 1. Installazione rapida (script automatico)

```bash
# Clona il repository
git clone https://github.com/Luca82box/Gufobox-3.0.git
cd Gufobox-3.0

# Esegui lo script di installazione (richiede sudo)
sudo bash scripts/install-raspberry.sh
```

Lo script esegue automaticamente:

1. **Pacchetti apt** — letti dai manifest `scripts/packages-*.txt`:
   - `packages-base.txt` — Python, ffmpeg, mpv, nodejs, rete, Bluetooth
   - `packages-gpio.txt` — GPIO, pulsanti, LED, SPI, audio ALSA
   - `packages-piper.txt` — dipendenze di sistema per Piper TTS
2. **Virtualenv Python** — crea `venv/` e installa `requirements.txt` + `requirements-hw.txt`
3. **Frontend Vue** — `npm ci && npm run build`
4. **Servizio systemd** — `gufobox.service` abilitato all'avvio

---

## 2. Configurazione post-installazione

Dopo l'installazione lo script crea `.env` da `.env.example`.
**Devi configurare almeno questi valori prima di avviare GufoBox:**

```bash
nano .env
```

```ini
# Chiave API OpenAI (obbligatoria per Story Studio e chat AI)
OPENAI_API_KEY=sk-...

# Chiave segreta Flask (cambia con un valore casuale lungo!)
GUFOBOX_SECRET_KEY=cambia-questo-con-un-valore-sicuro
```

Avvia il servizio:

```bash
sudo systemctl start gufobox
sudo systemctl status gufobox

# Log in tempo reale
journalctl -u gufobox -f
```

Accedi all'interfaccia: `http://gufobox.local:5000` oppure `http://<IP>:5000`

---

## 3. Installazione Piper TTS offline

Piper permette la sintesi vocale senza internet (fallback offline).

### 3a. Installazione automatica (consigliata)

1. Vai su **Pannello Admin → Voce offline**.
2. Clicca **"Scarica binario automaticamente"**.
   - Scarica `piper_linux_aarch64.tar.gz` da GitHub Releases.
   - Estrae binario + librerie condivise + dati espeak-ng in `data/piper_bin/`.
3. Clicca **"Scarica voce automaticamente"** e scegli `it_IT-paola-medium` (consigliata).
   - Scarica `.onnx` e `.onnx.json` da HuggingFace in `data/piper_voices/`.
4. Nelle impostazioni seleziona la voce appena scaricata e attiva **"Voce offline abilitata"**.

### 3b. Installazione manuale (senza internet)

Se il Raspberry Pi non ha accesso a internet puoi provvedere i file manualmente:

```bash
# Su un altro PC con internet, scarica l'archivio Piper per ARM64:
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz

# Scarica una voce italiana:
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json
```

Copia i file sul Raspberry Pi (es. via `scp`), poi:

1. **Binario** — vai su **Pannello Admin → Voce offline → Carica asset Piper**.
   - Seleziona directory `bin` e carica **tutti** i file estratti dall'archivio tar.gz
     (binario `piper`, `libonnxruntime.so.*`, `libpiper_phonemize.so.*`, cartella `espeak-ng-data/`).
   - Oppure estrai manualmente: `tar -xzf piper_linux_aarch64.tar.gz -C data/piper_bin/ --strip-components=1`

2. **Voce** — vai su **Pannello Admin → Voce offline → Carica asset Piper**.
   - Seleziona directory `voices` e carica `it_IT-paola-medium.onnx` e `it_IT-paola-medium.onnx.json`.

> **Nota:** Piper richiede obbligatoriamente **sia** il file `.onnx` (modello) **sia** il file
> `.onnx.json` (configurazione) per ogni voce. L'endpoint di stato (`/api/tts/offline/status`)
> riporta esplicitamente se uno dei due file è mancante.

### 3c. Verifica installazione Piper

```bash
# Testa il binario direttamente
data/piper_bin/piper --version

# Oppure usa l'endpoint API
curl http://localhost:5000/api/tts/offline/status | python3 -m json.tool
```

Il campo `piper_available: true` conferma che il binario risponde.
Il campo `voices_status` mostra per ogni voce se sia il `.onnx` che il `.onnx.json` sono presenti.

---

## 4. Manifest pacchetti (personalizzazione)

I pacchetti apt installati dallo script sono definiti in file di testo nella cartella `scripts/`:

| File | Contenuto |
|---|---|
| `packages-base.txt` | Dipendenze base (Python, ffmpeg, mpv, nodejs, rete) |
| `packages-gpio.txt` | GPIO, pulsanti, LED, SPI, audio ALSA |
| `packages-piper.txt` | Dipendenze di sistema per Piper TTS |

**Formato:**
- Una riga = un pacchetto apt
- Righe vuote e commenti (`#`) vengono ignorati
- Pacchetti con `?` finale sono opzionali (skip se non trovati, senza errore)

Per aggiungere pacchetti personalizzati modifica i file prima di eseguire lo script.

---

## 5. Opzioni avanzate dello script

```bash
sudo bash scripts/install-raspberry.sh --help

# Salta apt (solo aggiornamento pip + npm)
sudo bash scripts/install-raspberry.sh --skip-apt

# Senza systemd (solo dipendenze)
sudo bash scripts/install-raspberry.sh --skip-service

# Utente personalizzato
sudo bash scripts/install-raspberry.sh --user pi

# Directory personalizzata
sudo bash scripts/install-raspberry.sh --project-dir /home/pi/Gufobox-3.0
```

---

## 6. Risoluzione problemi

### Story Studio: errore "Servizio AI non disponibile"

- Verifica che `OPENAI_API_KEY` sia configurata in `.env` o nel pannello **Impostazioni AI**.
- Riavvia il servizio: `sudo systemctl restart gufobox`
- Controlla i log: `journalctl -u gufobox -f`

### Story Studio: selezione modello AI

Nel form di creazione storia usa il menu **"Modello AI"** per scegliere tra:
- `gpt-4o` — qualità massima (default)
- `gpt-4o-mini` — più veloce, qualità alta
- `gpt-4-turbo` — stabile
- `gpt-3.5-turbo` — economico, qualità base

Se il modello selezionato non è disponibile/accessibile, la generazione fallisce
con un messaggio italiano chiaramente leggibile.

### Piper: "File mancanti per la voce"

Se lo stato mostra `voices_status: {"it_IT-paola-medium": {"ok": false, "missing": [...]}}`:
- Scarica il file mancante tramite **"Scarica voce automaticamente"** nel pannello Voce offline.
- Oppure carica manualmente entrambi i file `.onnx` e `.onnx.json`.

### Piper: binario non risponde

- Verifica che il binario sia per ARM64: `file data/piper_bin/piper`
- Verifica permessi: `ls -la data/piper_bin/piper` (deve avere bit eseguibile)
- Verifica librerie condivise: `ldd data/piper_bin/piper`
- Reinstalla tramite "Scarica binario automaticamente" nel pannello Voce offline.

### GPIO / hardware non rilevato

- Verifica che `i2c` e `spi` siano abilitati: `sudo raspi-config` → Interface Options
- Per RFID (MFRC522): abilita SPI e installa `pip install mfrc522`
- Controlla i log hardware: `journalctl -u gufobox -f | grep -i gpio`

---

## 7. Aggiornamento

```bash
cd /path/to/Gufobox-3.0
git pull
sudo bash scripts/install-raspberry.sh --skip-apt --skip-service
sudo systemctl restart gufobox
```

---

*Documentazione aggiornata — GufoBox 3.0*
