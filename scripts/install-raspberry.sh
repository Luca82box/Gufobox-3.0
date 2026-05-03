#!/usr/bin/env bash
# =============================================================================
# install-raspberry.sh — GufoBox 3.0
#
# Script di installazione completa su Raspberry Pi OS (Debian/bookworm).
#
# Installa:
#   - Pacchetti di sistema (apt): Python 3, Node.js, mpv, gpio, rfid, led, audio...
#   - Dipendenze Python (pip): requirements.txt + requirements-hw.txt
#   - Frontend Vue (npm build)
#   - Servizio systemd gufobox (opzionale)
#
# Utilizzo:
#   bash scripts/install-raspberry.sh [--skip-apt] [--skip-npm] [--skip-service]
#
# Opzioni:
#   --skip-apt       Salta l'installazione dei pacchetti apt (per aggiornamenti veloci)
#   --skip-npm       Salta il build del frontend Vue
#   --skip-service   Salta la creazione/abilitazione del servizio systemd
#   --no-venv        Non crea/usa un virtualenv Python (usa il Python di sistema)
#   --user USER      Utente che eseguirà il servizio (default: gufobox)
#   --project-dir D  Directory del progetto (default: directory dello script/..)
#
# Esempi:
#   bash scripts/install-raspberry.sh
#   bash scripts/install-raspberry.sh --skip-service
#   bash scripts/install-raspberry.sh --user pi --project-dir /home/pi/Gufobox-3.0
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Argomenti
# ---------------------------------------------------------------------------
SKIP_APT=false
SKIP_NPM=false
SKIP_SERVICE=false
USE_VENV=true
SERVICE_USER="gufobox"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-apt)     SKIP_APT=true ;;
        --skip-npm)     SKIP_NPM=true ;;
        --skip-service) SKIP_SERVICE=true ;;
        --no-venv)      USE_VENV=false ;;
        --user)         SERVICE_USER="$2"; shift ;;
        --project-dir)  PROJECT_DIR="$2"; shift ;;
        -h|--help)
            sed -n '/^# ====/,/^# ====/p' "$0" | head -40
            exit 0 ;;
        *) echo "Opzione sconosciuta: $1"; exit 1 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Colori
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${YELLOW}=== $* ===${NC}"; }

# ---------------------------------------------------------------------------
# Verifica prerequisiti
# ---------------------------------------------------------------------------
section "Verifica prerequisiti"

if [[ $EUID -ne 0 ]]; then
    error "Questo script deve essere eseguito come root (sudo)."
    echo "  Uso: sudo bash $0"
    exit 1
fi

info "Directory progetto: ${PROJECT_DIR}"
if [[ ! -f "${PROJECT_DIR}/main.py" ]]; then
    error "main.py non trovato in ${PROJECT_DIR}. Verifica --project-dir."
    exit 1
fi
ok "Progetto trovato."

# ---------------------------------------------------------------------------
# Pacchetti di sistema (apt)
# ---------------------------------------------------------------------------
if [[ "${SKIP_APT}" == false ]]; then
    section "Installazione pacchetti di sistema (apt)"
    info "Aggiornamento lista pacchetti..."
    apt-get update -qq

    info "Installazione dipendenze base..."
    apt-get install -y \
        python3 python3-venv python3-pip python3-dev \
        git curl wget \
        ffmpeg mpv \
        nodejs npm \
        network-manager \
        bluez bluez-tools \
        avahi-daemon \
        i2c-tools \
        build-essential \
        libssl-dev libffi-dev

    info "Installazione dipendenze GPIO/hardware..."
    # python3-gpiozero e python3-lgpio sono i driver GPIO principali su Raspberry Pi OS bookworm
    apt-get install -y \
        python3-gpiozero \
        python3-lgpio \
        i2c-tools \
        python3-spidev || warn "Alcuni pacchetti GPIO potrebbero non essere disponibili su questa versione."

    # RPi.GPIO: disponibile come python3-rpi.gpio su sistemi più vecchi
    apt-get install -y python3-rpi.gpio 2>/dev/null || \
        warn "python3-rpi.gpio non disponibile (normale su Raspberry Pi OS bookworm recente — lgpio è il sostituto)."

    # pigpio: non sempre disponibile come pacchetto apt (dipende dalla distro)
    # Se non disponibile, pip install pigpio funziona comunque (vedi requirements-hw.txt)
    apt-get install -y pigpio python3-pigpio 2>/dev/null || \
        warn "pigpio apt non disponibile — verrà installato via pip se necessario."

    # libasound2-dev per audio via ALSA (utile per audio diretto su RPi)
    apt-get install -y libasound2-dev libportaudio2 2>/dev/null || true

    ok "Pacchetti di sistema installati."
else
    warn "Installazione apt saltata (--skip-apt)."
fi

# ---------------------------------------------------------------------------
# Virtualenv Python
# ---------------------------------------------------------------------------
section "Configurazione ambiente Python"

PYTHON_BIN="python3"
PIP_BIN="pip3"
VENV_DIR="${PROJECT_DIR}/venv"

if [[ "${USE_VENV}" == true ]]; then
    if [[ ! -d "${VENV_DIR}" ]]; then
        info "Creazione virtualenv Python in ${VENV_DIR}..."
        python3 -m venv "${VENV_DIR}"
        ok "Virtualenv creato."
    else
        info "Virtualenv già esistente in ${VENV_DIR}."
    fi
    PYTHON_BIN="${VENV_DIR}/bin/python"
    PIP_BIN="${VENV_DIR}/bin/pip"
fi

info "Aggiornamento pip, setuptools e wheel..."
"${PIP_BIN}" install --upgrade pip setuptools wheel -q

info "Installazione dipendenze Python (requirements.txt)..."
"${PIP_BIN}" install -r "${PROJECT_DIR}/requirements.txt" -q
ok "Dipendenze Python base installate."

info "Installazione dipendenze hardware Python (requirements-hw.txt)..."
# Queste dipendenze possono fallire su non-RPi; usiamo || true per non bloccare
"${PIP_BIN}" install -r "${PROJECT_DIR}/requirements-hw.txt" -q 2>/dev/null || \
    warn "Alcune dipendenze hardware (requirements-hw.txt) non installate — normale su non-RPi."
ok "Dipendenze Python hardware installate (dove disponibili)."

# ---------------------------------------------------------------------------
# Frontend Vue
# ---------------------------------------------------------------------------
if [[ "${SKIP_NPM}" == false ]]; then
    section "Build Frontend Vue"
    FRONTEND_DIR="${PROJECT_DIR}/frontend"
    if [[ -f "${FRONTEND_DIR}/package.json" ]]; then
        info "Installazione dipendenze npm..."
        cd "${FRONTEND_DIR}"
        # Usa 'npm ci' per install deterministico se il lockfile è presente
        if [[ -f "package-lock.json" ]]; then
            npm ci --silent
        else
            npm install --silent
        fi
        info "Build produzione frontend..."
        npm run build
        cd "${PROJECT_DIR}"
        ok "Frontend costruito in ${FRONTEND_DIR}/dist"
    else
        warn "package.json non trovato in ${FRONTEND_DIR}. Salto build frontend."
    fi
else
    warn "Build npm saltato (--skip-npm)."
fi

# ---------------------------------------------------------------------------
# Permessi
# ---------------------------------------------------------------------------
section "Configurazione permessi"

if id "${SERVICE_USER}" &>/dev/null; then
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PROJECT_DIR}"
    ok "Permessi impostati per utente ${SERVICE_USER}."
else
    warn "Utente '${SERVICE_USER}' non trovato. Permessi non modificati."
fi

# ---------------------------------------------------------------------------
# File .env
# ---------------------------------------------------------------------------
section "Configurazione .env"

ENV_FILE="${PROJECT_DIR}/.env"
ENV_EXAMPLE="${PROJECT_DIR}/.env.example"
if [[ ! -f "${ENV_FILE}" ]] && [[ -f "${ENV_EXAMPLE}" ]]; then
    cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    warn "Creato .env da .env.example — RICORDA di configurare OPENAI_API_KEY e GUFOBOX_SECRET_KEY!"
elif [[ ! -f "${ENV_FILE}" ]]; then
    warn ".env non trovato e .env.example non presente. Crea manualmente il file .env."
else
    info ".env già presente."
fi

# ---------------------------------------------------------------------------
# Servizio systemd
# ---------------------------------------------------------------------------
if [[ "${SKIP_SERVICE}" == false ]]; then
    section "Configurazione servizio systemd"

    SERVICE_FILE="/etc/systemd/system/gufobox.service"
    EXEC_PYTHON="${VENV_DIR}/bin/python"
    if [[ "${USE_VENV}" == false ]]; then
        EXEC_PYTHON="$(which python3)"
    fi

    info "Scrittura ${SERVICE_FILE}..."
    cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=GufoBox 3.0 — Smart Speaker Educativo
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment=PATH=${VENV_DIR}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EnvironmentFile=-${PROJECT_DIR}/.env
ExecStart=${EXEC_PYTHON} ${PROJECT_DIR}/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable gufobox.service
    ok "Servizio gufobox abilitato. Avvia con: sudo systemctl start gufobox"
else
    warn "Configurazione servizio systemd saltata (--skip-service)."
fi

# ---------------------------------------------------------------------------
# Riepilogo
# ---------------------------------------------------------------------------
section "Installazione completata"
echo ""
echo -e "  Progetto:     ${PROJECT_DIR}"
echo -e "  Virtualenv:   ${VENV_DIR}"
echo -e "  Utente:       ${SERVICE_USER}"
echo ""
echo -e "${YELLOW}Passi successivi:${NC}"
echo "  1. Configura il file .env con la tua OPENAI_API_KEY"
echo "  2. Avvia GufoBox:  sudo systemctl start gufobox"
echo "  3. Controlla log:  journalctl -u gufobox -f"
echo "  4. Accedi via:     http://gufobox.local:5000  (o IP:5000)"
echo ""
echo -e "${GREEN}Installazione GufoBox completata con successo!${NC}"
