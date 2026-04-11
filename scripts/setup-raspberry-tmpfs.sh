#!/usr/bin/env bash
# =============================================================================
# setup-raspberry-tmpfs.sh — GufoBox 3.0
#
# Monta in RAM (tmpfs) le directory dei log e degli upload temporanei per
# ridurre le scritture sulla microSD su Raspberry Pi OS.
#
# Utilizzo:
#   bash scripts/setup-raspberry-tmpfs.sh
#
# Richiede sudo per modificare /etc/fstab e montare i filesystem.
# =============================================================================
set -euo pipefail

LOGS_DIR="/home/gufobox/data/logs"
TMP_UPLOADS_DIR="/home/gufobox/data/tmp_uploads"
FSTAB="/etc/fstab"

# Rileva uid/gid dell'utente gufobox (o dell'utente corrente come fallback)
if id gufobox &>/dev/null; then
    TARGET_UID=$(id -u gufobox)
    TARGET_GID=$(id -g gufobox)
else
    TARGET_UID=$(id -u)
    TARGET_GID=$(id -g)
    echo "Avviso: utente 'gufobox' non trovato. Uso uid/gid dell'utente corrente: ${TARGET_UID}:${TARGET_GID}"
fi

echo "=== Configurazione tmpfs per GufoBox ==="
echo "  logs dir:        ${LOGS_DIR}"
echo "  tmp_uploads dir: ${TMP_UPLOADS_DIR}"
echo "  uid:gid:         ${TARGET_UID}:${TARGET_GID}"
echo ""

# Crea le directory se non esistono
mkdir -p "${LOGS_DIR}"
mkdir -p "${TMP_UPLOADS_DIR}"

# Backup di fstab
echo "Backup di ${FSTAB} → ${FSTAB}.backup"
sudo cp "${FSTAB}" "${FSTAB}.backup"

# Aggiunge le righe tmpfs solo se non già presenti
LOGS_ENTRY="tmpfs ${LOGS_DIR} tmpfs defaults,noatime,nosuid,size=32m,uid=${TARGET_UID},gid=${TARGET_GID},mode=0755 0 0"
TMP_ENTRY="tmpfs ${TMP_UPLOADS_DIR} tmpfs defaults,noatime,nosuid,size=64m,uid=${TARGET_UID},gid=${TARGET_GID},mode=0755 0 0"

if grep -qF "${LOGS_DIR}" "${FSTAB}"; then
    echo "Voce tmpfs per ${LOGS_DIR} già presente in fstab, salto."
else
    echo "${LOGS_ENTRY}" | sudo tee -a "${FSTAB}" > /dev/null
    echo "Aggiunta voce tmpfs per ${LOGS_DIR}"
fi

if grep -qF "${TMP_UPLOADS_DIR}" "${FSTAB}"; then
    echo "Voce tmpfs per ${TMP_UPLOADS_DIR} già presente in fstab, salto."
else
    echo "${TMP_ENTRY}" | sudo tee -a "${FSTAB}" > /dev/null
    echo "Aggiunta voce tmpfs per ${TMP_UPLOADS_DIR}"
fi

# Monta i filesystem senza riavviare
echo ""
echo "Eseguo mount -a..."
sudo mount -a

echo ""
echo "Verifica mount:"
mount | grep gufobox || echo "(nessun mount gufobox trovato — controllare fstab o il percorso)"

echo ""
echo "=== Configurazione tmpfs completata ==="
echo "Nota: i dati in tmpfs vengono persi al riavvio. Adatto per log e upload temporanei."
