# 🦉 GufoBox 3.0 — Mappa Completa Pin Raspberry Pi

Documento di riferimento tecnico per tutti i pin GPIO utilizzati dal progetto GufoBox 3.0.

**Ultimo aggiornamento:** Aprile 2026

---

## 🎛️ 1. Pulsanti Fisici

> Fonte: `hw/buttons.py`

| GPIO | Pin fisico | Componente | Funzione |
|------|------------|------------|----------|
| GPIO3 | Pin 5 | Pulsante POWER | Accensione / Spegnimento SO. Wake da standby. Disattiva sveglia attiva |
| GPIO5 | Pin 29 | Pulsante PLAY/PAUSA | Play/Pausa riproduzione. Snooze sveglia (5 min) |
| GPIO6 | Pin 31 | Pulsante NEXT | Traccia successiva (click), Volume + (tenuto premuto) |
| GPIO13 | Pin 33 | Pulsante PREV | Traccia precedente (click), Volume − (tenuto premuto) |

---

## 🔊 2. Amplificatore PAM8406

> Fonte: `hw/amp.py`

| GPIO | Pin fisico | Componente | Funzione |
|------|------------|------------|----------|
| GPIO20 | Pin 38 | Amp TRIGGER | Accende/spegne l'alimentazione all'amplificatore |
| GPIO26 | Pin 37 | Amp MUTE | Mette in muto il PAM8406 (anti-pop) |

---

## 💡 3. Striscia LED WS2813

> Fonte: `hw/led.py`

| GPIO | Pin fisico | Componente | Funzione |
|------|------------|------------|----------|
| GPIO12 | Pin 32 | LED DATA (PWM0) | Segnale dati per striscia NeoPixel WS2813 (12 LED, 800kHz, DMA 10, canale PWM 0) |

---

## 📡 4. Lettore RFID RC522 — Bus SPI0

> Fonte: `hw/rfid.py`

| GPIO | Pin fisico | Componente | Funzione |
|------|------------|------------|----------|
| GPIO8 (CE0) | Pin 24 | RFID SDA/CS | Chip Select SPI — seleziona il lettore RC522 |
| GPIO11 (SCLK) | Pin 23 | RFID SCK | Clock SPI |
| GPIO10 (MOSI) | Pin 19 | RFID MOSI | Master Out Slave In — dati verso RC522 |
| GPIO9 (MISO) | Pin 21 | RFID MISO | Master In Slave Out — dati dal RC522 |
| GPIO25 | Pin 22 | RFID RST | Reset del modulo RC522 (default libreria mfrc522) |

---

## 🔋 5. Batteria MAX17048 — Bus I2C1

> Fonte: `hw/battery.py`

| GPIO | Pin fisico | Componente | Funzione |
|------|------------|------------|----------|
| GPIO2 (SDA1) | Pin 3 | Batteria SDA | Linea dati I2C per fuel gauge MAX17048 (indirizzo 0x36) |
| GPIO3 (SCL1) | Pin 5 | Batteria SCL | Linea clock I2C (condiviso con pulsante POWER) |

> ⚠️ **Nota:** GPIO3 è condiviso tra la linea clock I2C (SCL1) e il pulsante POWER. Questo è possibile perché il bus I2C usa resistenze di pull-up e il pulsante agisce da segnale di wake-up/power.

---

## 🗺️ 6. Schema Visivo Header 40 Pin

```
                    +-----+-----+
             3.3V   |  1  |  2  | 5V
   🔋 I2C SDA (GPIO2) |  3  |  4  | 5V
   ⏻🔋 I2C SCL/POWER (GPIO3) |  5  |  6  | GND
                     |  7  |  8  | (UART TX)
              GND    |  9  | 10  | (UART RX)
                     | 11  | 12  |
                     | 13  | 14  | GND
                     | 15  | 16  |
             3.3V    | 17  | 18  |
   📡 RFID MOSI (GPIO10) | 19  | 20  | GND
   📡 RFID MISO (GPIO9)  | 21  | 22  | 📡 RFID RST (GPIO25)
   📡 RFID SCK (GPIO11)  | 23  | 24  | 📡 RFID CS (GPIO8)
              GND    | 25  | 26  |
                     | 27  | 28  |
   ▶️ PLAY/PAUSA (GPIO5) | 29  | 30  | GND
   ⏭️ NEXT (GPIO6)       | 31  | 32  | 💡 LED DATA (GPIO12)
   ⏮️ PREV (GPIO13)      | 33  | 34  | GND
                     | 35  | 36  |
   🔇 AMP MUTE (GPIO26) | 37  | 38  | 🔊 AMP TRIGGER (GPIO20)
              GND    | 39  | 40  |
                    +-----+-----+
```

---

## 📋 7. Riepilogo per Bus/Protocollo

| Bus | GPIO usati | Periferica |
|-----|------------|------------|
| SPI0 | 8 (CS), 9 (MISO), 10 (MOSI), 11 (SCLK), 25 (RST) | Lettore RFID RC522 |
| I2C1 | 2 (SDA), 3 (SCL) | Fuel gauge batteria MAX17048 |
| PWM0 | 12 | Striscia LED WS2813 (12 LED) |
| GPIO digitale | 5, 6, 13, 3 | 4 pulsanti fisici |
| GPIO digitale | 20, 26 | Amplificatore PAM8406 (trigger + mute) |
| Bluetooth | — (integrato) | Casse/cuffie BT esterne + modalità speaker |
| Wi-Fi | — (integrato) | Connessione rete + hotspot AP |

> **Totale GPIO utilizzati: 13** (su 26 disponibili)

---

## ⚠️ 8. Note Importanti

- **GPIO3 condiviso I2C/Power:** GPIO3 funge sia da SCL del bus I2C1 (linea clock per MAX17048) sia da pulsante POWER. Questo è supportato dall'hardware del Raspberry Pi grazie alle resistenze di pull-up interne del pin.
- **SPI abilitato:** Il bus SPI0 deve essere abilitato tramite `raspi-config` → *Interface Options* → *SPI* → *Enable* prima di poter usare il lettore RFID RC522.
- **I2C abilitato:** Il bus I2C1 deve essere abilitato tramite `raspi-config` → *Interface Options* → *I2C* → *Enable* prima di poter usare il fuel gauge MAX17048.
- **LED WS2813 — permessi root:** La libreria `rpi-ws281x` che controlla la striscia LED WS2813 richiede permessi root/sudo per accedere al DMA e al PWM hardware. Avviare il servizio GufoBox con `sudo`.
- **Amplificatore — logica anti-pop:** Per evitare rumori durante l'accensione/spegnimento dell'amplificatore PAM8406, la sequenza corretta è: mettere in MUTE (GPIO26 HIGH) prima di spegnere il TRIGGER (GPIO20 LOW), e viceversa accendere il TRIGGER prima di disattivare il MUTE.

---

## 📄 9. Come Convertire in PDF

### VS Code — Estensione "Markdown PDF"

1. Installa l'estensione **Markdown PDF** (`yzane.markdown-pdf`) da VS Code Marketplace
2. Apri questo file `docs/PINOUT.md` in VS Code
3. Premi `Ctrl+Shift+P` (o `Cmd+Shift+P` su Mac) per aprire la palette comandi
4. Cerca e seleziona: **Markdown PDF: Export (pdf)**
5. Il PDF verrà generato nella stessa cartella del file Markdown

### Pandoc (da terminale)

```bash
# Installa pandoc (se non già presente)
sudo apt install pandoc texlive-latex-base texlive-fonts-recommended

# Converti in PDF
pandoc docs/PINOUT.md -o docs/PINOUT.pdf --pdf-engine=pdflatex

# Oppure con wkhtmltopdf (migliore supporto emoji)
pandoc docs/PINOUT.md -o docs/PINOUT.pdf --pdf-engine=wkhtmltopdf
```

### Stampa dal browser GitHub

1. Apri il file `docs/PINOUT.md` su GitHub nel browser
2. Il file viene renderizzato automaticamente come HTML formattato
3. Usa la funzione di stampa del browser (`Ctrl+P` / `Cmd+P`)
4. Seleziona **"Salva come PDF"** come destinazione di stampa
5. Assicurati di abilitare la stampa degli sfondi per mantenere i colori delle tabelle
