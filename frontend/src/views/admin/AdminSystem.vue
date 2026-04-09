<template>
  <div class="admin-system">

    <div class="header-section">
      <h2>Sistema ⚙️</h2>
      <p>Gestisci aggiornamenti, backup, rollback, alimentazione e sicurezza.</p>
    </div>

    <!-- Standby banner -->
    <div v-if="inStandby" class="standby-banner">
      🌙 <strong>GufoBox in standby applicativo</strong> — clicca "Riavvia" o "Standby" per interagire.
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- Power controls -->
    <div class="card">
      <h3>Alimentazione 🔌</h3>
      <div class="power-row">
        <button class="btn-power standby" @click="sendAction('standby')" :disabled="powerBusy">🌙 Standby</button>
        <button class="btn-power reboot" @click="sendAction('reboot')" :disabled="powerBusy">🔄 Riavvia</button>
        <button class="btn-power shutdown" @click="sendAction('shutdown')" :disabled="powerBusy">⏻ Spegni</button>
      </div>
    </div>

    <!-- Sicurezza PIN -->
    <div class="card">
      <h3>Sicurezza PIN 🔐</h3>
      <p class="card-desc">Modifica il PIN di accesso all'area admin (da 4 a 8 cifre numeriche).</p>
      <div class="pin-change-grid">
        <div class="form-group">
          <label>PIN attuale</label>
          <input
            type="password"
            v-model="pinCurrent"
            class="input-pin"
            placeholder="PIN attuale"
            maxlength="8"
            inputmode="numeric"
            pattern="[0-9]*"
          />
        </div>
        <div class="form-group">
          <label>Nuovo PIN</label>
          <input
            type="password"
            v-model="pinNew"
            class="input-pin"
            placeholder="Nuovo PIN (4-8 cifre)"
            maxlength="8"
            inputmode="numeric"
            pattern="[0-9]*"
          />
        </div>
        <div class="form-group">
          <label>Conferma nuovo PIN</label>
          <input
            type="password"
            v-model="pinConfirm"
            class="input-pin"
            placeholder="Ripeti nuovo PIN"
            maxlength="8"
            inputmode="numeric"
            pattern="[0-9]*"
          />
        </div>
      </div>
      <div v-if="pinChangeError" class="pin-change-error">⚠️ {{ pinChangeError }}</div>
      <button class="btn-pin-change" @click="changePin" :disabled="pinChangeBusy">
        {{ pinChangeBusy ? '⏳ Salvataggio...' : '🔐 Cambia PIN' }}
      </button>
    </div>

    <!-- OTA Update -->
    <div class="card">
      <h3>Aggiornamento OTA ⬆️</h3>

      <!-- Descrizione cosa include l'aggiornamento -->
      <div class="ota-info-box">
        <strong>Cosa comprende l'aggiornamento?</strong>
        <ul class="ota-includes-list">
          <li>📦 <strong>Aggiorna App</strong> — scarica l'ultima versione del codice backend Python e frontend Vue da GitHub (git pull), reinstalla le dipendenze Python e ricompila il frontend</li>
          <li>🛡️ <strong>Aggiorna Sistema</strong> — aggiorna i pacchetti di sistema Raspberry Pi/Debian tramite apt-get (sicuro, non riavvia automaticamente)</li>
        </ul>
        <p class="ota-tip">💡 Viene creato un backup automatico prima di ogni aggiornamento. Puoi ripristinare dalla sezione Backup se qualcosa va storto.</p>
      </div>

      <div class="ota-status-bar" :class="otaStatus.status">
        <span>Stato: <strong>{{ otaStatusLabel }}</strong></span>
        <span v-if="otaStatus.mode"> — Modalità: {{ otaStatus.mode }}</span>
        <span v-if="otaStatus.finished_at"> — Finito: {{ formatDate(otaStatus.finished_at) }}</span>
      </div>

      <!-- Progress bar shown while running -->
      <div v-if="otaRunning" class="ota-progress">
        <div class="ota-progress-bar">
          <div class="ota-progress-fill" :style="{ width: (otaStatus.progress_percent || 0) + '%' }"></div>
        </div>
        <div class="ota-progress-info">
          <span class="ota-progress-pct">{{ otaStatus.progress_percent || 0 }}%</span>
          <span class="progress-desc">{{ otaStatus.description || 'Aggiornamento in corso...' }}</span>
        </div>
      </div>

      <!-- Last error if any -->
      <div v-if="otaStatus.last_error" class="ota-error-box">
        ⚠️ Ultimo errore: {{ otaStatus.last_error }}
      </div>

      <div class="ota-actions">
        <button
          class="btn-ota"
          @click="startOta('app')"
          :disabled="otaRunning"
        >
          📦 Aggiorna App (git pull)
        </button>
        <button
          class="btn-ota"
          @click="startOta('system_safe')"
          :disabled="otaRunning"
        >
          🛡️ Aggiorna Sistema (apt)
        </button>
        <button class="btn-refresh" @click="loadOtaStatus">🔄</button>
      </div>

      <div v-if="showLog" class="ota-log-box">
        <pre>{{ otaLog }}</pre>
      </div>
      <button class="btn-link" @click="toggleLog">
        {{ showLog ? '▲ Nascondi log' : '▼ Mostra log OTA' }}
      </button>
    </div>

    <!-- OTA da file -->
    <div class="card">
      <h3>Aggiornamento da File 📁</h3>
      <p class="card-desc">Carica un package <code>.zip</code> o <code>.tar.gz</code> per aggiornare l'app manualmente. Il processo: validazione archivio → backup automatico → copia file.</p>

      <!-- Upload area -->
      <div class="file-upload-area">
        <input
          ref="fileInputRef"
          type="file"
          accept=".zip,.tar.gz"
          style="display:none"
          @change="onFileSelected"
        />
        <button class="btn-ota" @click="fileInputRef.click()" :disabled="otaRunning || uploadBusy">
          📂 Seleziona package
        </button>
        <span v-if="selectedFile" class="file-selected-name">{{ selectedFile.name }}</span>
        <button
          v-if="selectedFile"
          class="btn-ota btn-upload"
          @click="uploadPackage"
          :disabled="otaRunning || uploadBusy"
        >
          {{ uploadBusy ? '⏳ Caricamento...' : '⬆️ Carica' }}
        </button>
      </div>

      <!-- Upload error -->
      <div v-if="uploadError" class="ota-error-box">⚠️ {{ uploadError }}</div>

      <!-- Staged package info -->
      <div v-if="otaStatus.staged_filename && !uploadError" class="staged-info">
        <span class="staged-label">Package caricato:</span>
        <span class="staged-name">{{ otaStatus.staged_filename }}</span>
        <span v-if="otaStatus.staged_at" class="staged-date">{{ formatDate(otaStatus.staged_at) }}</span>
      </div>

      <!-- Apply section -->
      <div v-if="canApplyUploaded" class="ota-apply-section">
        <p class="apply-desc">Il package è pronto. Clicca "Applica" per avviare l'aggiornamento (backup automatico prima dell'apply).</p>
        <div class="ota-actions">
          <button
            class="btn-ota btn-apply"
            @click="applyUploaded"
            :disabled="otaRunning || uploadBusy"
          >
            ✅ Applica Package
          </button>
        </div>
      </div>

      <!-- In-progress for file OTA -->
      <div v-if="otaRunning && otaStatus.mode === 'file'" class="ota-progress">
        <div class="ota-progress-bar">
          <div class="ota-progress-fill" :style="{ width: (otaStatus.progress_percent || 0) + '%' }"></div>
        </div>
        <div class="ota-progress-info">
          <span class="ota-progress-pct">{{ otaStatus.progress_percent || 0 }}%</span>
          <span class="progress-desc">{{ otaStatus.description || 'Apply in corso...' }}</span>
        </div>
      </div>

      <!-- File OTA result -->
      <div v-if="otaStatus.mode === 'file' && otaStatus.status === 'success'" class="ota-success-box">
        ✅ {{ otaStatus.description }}
      </div>
      <div v-if="otaStatus.mode === 'file' && otaStatus.status === 'failed'" class="ota-error-box">
        ❌ {{ otaStatus.last_error || otaStatus.description }}
      </div>
    </div>

    <!-- Backups -->
    <div class="card">
      <div class="card-header">
        <h3>Backup 💾</h3>
        <button class="btn-refresh" @click="loadBackups">🔄</button>
      </div>

      <div v-if="backups.length === 0" class="empty-state">
        Nessun backup disponibile. Viene creato automaticamente prima di ogni aggiornamento.
      </div>

      <div v-else class="backups-list">
        <div v-for="b in backups" :key="b.name" class="backup-item">
          <div class="backup-info">
            <span class="backup-name">{{ b.name }}</span>
            <span class="backup-meta">{{ formatDate(b.created_at) }} — {{ b.size_mb }} MB</span>
          </div>
          <div class="backup-actions">
            <button class="btn-rollback" @click="rollback(b.name)" :disabled="rollingBack">
              ↩️ Ripristina
            </button>
            <button class="btn-delete" @click="deleteBackup(b.name)">🗑️</button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

// Standby state
const inStandby = ref(false)
const powerBusy = ref(false)

async function loadStandbyStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/system/standby'))
    inStandby.value = data?.in_standby || false
  } catch (e) {
    // Not critical — may not be available
  }
}

// Power
async function sendAction(azione) {
  const labels = { standby: 'mettere in standby', reboot: 'riavviare', shutdown: 'spegnere' }
  if (!confirm(`Vuoi davvero ${labels[azione]} la GufoBox?`)) return
  powerBusy.value = true
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system', { azione }))
    if (azione === 'standby') {
      inStandby.value = true
      showSuccess('GufoBox in standby.')
    }
  } catch (e) {
    showError(extractApiError(e, `Errore durante l'operazione "${azione}"`))
  } finally {
    powerBusy.value = false
  }
}

// OTA
const otaStatus = ref({ status: 'idle', mode: null, started_at: null, finished_at: null, error: null, last_error: null, progress_percent: null, description: null, running: false, staged_filename: null, staged_at: null })
const otaLog = ref('')
const showLog = ref(false)
const rollingBack = ref(false)
let otaPollInterval = null

const otaRunning = computed(() => otaStatus.value.running || otaStatus.value.status === 'running' || otaStatus.value.status === 'validating' || otaStatus.value.status === 'applying')
const otaStatusLabel = computed(() => {
  const map = {
    idle: 'In attesa',
    running: 'In corso...',
    done: 'Completato ✅',
    error: 'Errore ❌',
    uploaded: 'Package caricato 📦',
    validating: 'Validazione...',
    applying: 'Apply in corso...',
    success: 'Completato ✅',
    failed: 'Fallito ❌',
  }
  return map[otaStatus.value.status] || otaStatus.value.status
})

async function loadOtaStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/system/ota/status'))
    otaStatus.value = data
    // Auto-poll while running
    if (data.running || data.status === 'running' || data.status === 'validating' || data.status === 'applying') {
      if (!otaPollInterval) {
        otaPollInterval = setInterval(loadOtaStatus, 3000)
      }
    } else {
      clearInterval(otaPollInterval)
      otaPollInterval = null
    }
  } catch (e) {
    console.error('Errore stato OTA:', extractApiError(e))
  }
}

async function startOta(mode) {
  if (!confirm(`Avviare aggiornamento in modalità "${mode}"?`)) return
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/ota/start', { mode }))
    setTimeout(loadOtaStatus, 2000)
  } catch (e) {
    showError(extractApiError(e, 'Errore avvio OTA'))
  }
}

async function toggleLog() {
  showLog.value = !showLog.value
  if (showLog.value) {
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/system/ota/log'))
      otaLog.value = data?.log || '(log vuoto)'
    } catch (e) {
      otaLog.value = extractApiError(e, 'Errore lettura log')
    }
  }
}

// ─── OTA da file ─────────────────────────────────────────────────────────────
const fileInputRef = ref(null)
const selectedFile = ref(null)
const uploadBusy = ref(false)
const uploadError = ref('')

const canApplyUploaded = computed(() =>
  !otaRunning.value &&
  !uploadBusy.value &&
  otaStatus.value.staged_filename &&
  ['uploaded', 'success', 'failed'].includes(otaStatus.value.status) &&
  otaStatus.value.mode === 'file'
)

function onFileSelected(event) {
  uploadError.value = ''
  const file = event.target.files?.[0]
  if (!file) return
  const name = file.name.toLowerCase()
  if (!name.endsWith('.zip') && !name.endsWith('.tar.gz')) {
    uploadError.value = `Estensione non consentita: "${file.name}". Usa .zip o .tar.gz`
    selectedFile.value = null
    return
  }
  selectedFile.value = file
}

async function uploadPackage() {
  if (!selectedFile.value) return
  uploadBusy.value = true
  uploadError.value = ''
  try {
    const api = getApi()
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    await guardedCall(() => api.post('/system/ota/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }))
    selectedFile.value = null
    if (fileInputRef.value) fileInputRef.value.value = ''
    await loadOtaStatus()
  } catch (e) {
    uploadError.value = extractApiError(e, 'Errore upload package')
  } finally {
    uploadBusy.value = false
  }
}

async function applyUploaded() {
  if (!confirm('Applicare il package caricato? Verrà creato un backup automatico prima di procedere.')) return
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/ota/apply_uploaded'))
    // Start polling
    setTimeout(loadOtaStatus, 1500)
    if (!otaPollInterval) {
      otaPollInterval = setInterval(loadOtaStatus, 3000)
    }
  } catch (e) {
    showError(extractApiError(e, 'Errore apply package'))
  }
}

// Backups
const backups = ref([])

async function loadBackups() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/system/backups'))
    backups.value = data?.backups || []
  } catch (e) {
    console.error('Errore caricamento backups:', extractApiError(e))
  }
}

async function deleteBackup(name) {
  if (!confirm(`Eliminare il backup "${name}"?`)) return
  clearFeedback()
  try {
    const api = getApi()
    await api.delete(`/system/backups/${name}`)
    await loadBackups()
    showSuccess(`Backup "${name}" eliminato.`)
  } catch (e) {
    showError(extractApiError(e, 'Errore eliminazione backup'))
  }
}

async function rollback(backupName) {
  if (!confirm(`Ripristinare l'app dal backup "${backupName}"?\nI file correnti verranno sovrascritti.`)) return
  rollingBack.value = true
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/rollback', { backup_name: backupName }))
    showSuccess('Rollback avviato. Riavvia la GufoBox per applicare le modifiche.')
  } catch (e) {
    showError(extractApiError(e, 'Errore rollback'))
  } finally {
    rollingBack.value = false
  }
}

function formatDate(isoStr) {
  if (!isoStr) return ''
  try {
    return new Date(isoStr).toLocaleString('it-IT')
  } catch {
    return isoStr
  }
}

// PIN change
const pinCurrent = ref('')
const pinNew = ref('')
const pinConfirm = ref('')
const pinChangeBusy = ref(false)
const pinChangeError = ref('')

async function changePin() {
  pinChangeError.value = ''
  const cur = pinCurrent.value.trim()
  const nw = pinNew.value.trim()
  const conf = pinConfirm.value.trim()
  if (!cur || !nw || !conf) {
    pinChangeError.value = 'Compila tutti i campi.'
    return
  }
  if (!/^\d{4,8}$/.test(nw)) {
    pinChangeError.value = 'Il nuovo PIN deve contenere solo cifre (4-8 caratteri).'
    return
  }
  if (nw !== conf) {
    pinChangeError.value = 'I due PIN non coincidono.'
    return
  }
  pinChangeBusy.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/auth/pin/change', {
      current_pin: cur,
      new_pin: nw,
    }))
    pinCurrent.value = ''
    pinNew.value = ''
    pinConfirm.value = ''
    showSuccess('PIN cambiato con successo! Effettua nuovamente il login.')
  } catch (e) {
    pinChangeError.value = extractApiError(e, 'Errore cambio PIN')
  } finally {
    pinChangeBusy.value = false
  }
}

onMounted(() => {
  loadStandbyStatus()
  loadOtaStatus()
  loadBackups()
})

onUnmounted(() => {
  clearInterval(otaPollInterval)
})
</script>

<style scoped>
.admin-system {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

/* Standby banner */
.standby-banner {
  background: #1e2a4a;
  border: 1px solid #3f51b5;
  border-radius: 10px;
  padding: 14px 18px;
  color: #8ab4f8;
  font-size: 0.95rem;
}

/* Feedback banner */
.banner {
  padding: 12px 16px;
  border-radius: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.95rem;
  gap: 10px;
}
.banner-error   { background: #3b1212; color: #ef9a9a; border: 1px solid #c62828; }
.banner-success { background: #1b3a1b; color: #a5d6a7; border: 1px solid #388e3c; }
.banner-warning { background: #3b2e0a; color: #ffe082; border: 1px solid #f9a825; }
.banner-info    { background: #1a2a3b; color: #90caf9; border: 1px solid #1565c0; }
.banner-close { background: none; border: none; cursor: pointer; opacity: 0.7; color: inherit; font-size: 1rem; padding: 0 4px; }
.banner-close:hover { opacity: 1; }

.card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.card h3 {
  margin-top: 0;
  color: #ffd27b;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
  margin-bottom: 15px;
}

.card-header h3 { border-bottom: none; padding-bottom: 0; margin: 0; color: #ffd27b; }

/* Power */
.power-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.btn-power {
  padding: 12px 20px;
  border: none;
  border-radius: 10px;
  font-weight: bold;
  font-size: 1rem;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-power:hover { opacity: 0.85; }
.btn-power.standby { background: #3f51b5; color: white; }
.btn-power.reboot { background: #ff9800; color: white; }
.btn-power.shutdown { background: #e53935; color: white; }

/* PIN Change */
.card-desc { color: #aaa; font-size: 0.9rem; margin: 0 0 15px 0; }

.pin-change-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 15px;
  margin-bottom: 15px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label { font-size: 0.9rem; color: #ccc; }

.input-pin {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 1.1rem;
  letter-spacing: 4px;
  width: 100%;
  box-sizing: border-box;
}

.input-pin:focus { outline: none; border-color: #ffd27b; }

.pin-change-error {
  color: #ef9a9a;
  background: #3b1212;
  border: 1px solid #c62828;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 0.9rem;
  margin-bottom: 12px;
}

.btn-pin-change {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 11px 22px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-pin-change:hover { opacity: 0.85; }
.btn-pin-change:disabled { background: #555; color: #888; cursor: not-allowed; }

/* OTA */
.ota-status-bar {
  background: #1e1e26;
  padding: 10px 15px;
  border-radius: 8px;
  font-size: 0.95rem;
  color: #ccc;
  margin-bottom: 15px;
  border-left: 4px solid #555;
}

.ota-status-bar.running { border-left-color: #ff9800; }
.ota-status-bar.done { border-left-color: #4caf50; }
.ota-status-bar.error { border-left-color: #e53935; }

/* OTA info description box */
.ota-info-box {
  background: rgba(63,81,181,0.1);
  border: 1px solid rgba(63,81,181,0.3);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
  font-size: 0.88rem;
  color: #bbb;
}

.ota-info-box strong {
  color: #fff;
  display: block;
  margin-bottom: 8px;
  font-size: 0.93rem;
}

.ota-includes-list {
  margin: 0 0 8px 0;
  padding-left: 6px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ota-includes-list li { color: #bbb; font-size: 0.84rem; line-height: 1.4; }

.ota-tip { margin: 8px 0 0; color: #888; font-size: 0.82rem; font-style: italic; }

.ota-progress {
  margin-bottom: 15px;
}

/* New improved progress bar */
.ota-progress-bar {
  background: #1a1a2e;
  border: 1px solid #3a3a50;
  border-radius: 8px;
  height: 13px;
  overflow: hidden;
  margin-bottom: 6px;
}

.ota-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3f51b5 0%, #ff9800 100%);
  border-radius: 8px;
  transition: width 0.6s ease;
  box-shadow: 0 0 8px rgba(255,152,0,0.35);
}

.ota-progress-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ota-progress-pct {
  font-size: 0.9rem;
  font-weight: 700;
  color: #ffd27b;
  min-width: 36px;
  font-variant-numeric: tabular-nums;
}

/* Keep legacy classes */
.progress-bar {
  background: #1e1e26;
  border-radius: 6px;
  height: 10px;
  overflow: hidden;
  margin-bottom: 6px;
}

.progress-fill {
  height: 100%;
  background: #ff9800;
  border-radius: 6px;
  transition: width 0.5s ease;
}

.progress-desc {
  color: #aaa;
  font-size: 0.85rem;
  margin: 0;
}

.ota-error-box {
  background: #2a1a1a;
  border: 1px solid #e53935;
  border-radius: 8px;
  padding: 10px 15px;
  color: #ff8a80;
  font-size: 0.9rem;
  margin-bottom: 12px;
}

.ota-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.btn-ota {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 10px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.95rem;
}

.btn-ota:disabled { background: #555; color: #888; cursor: not-allowed; }

.btn-refresh {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
}

.btn-link {
  background: transparent;
  border: none;
  color: #ffd27b;
  cursor: pointer;
  font-size: 0.9rem;
  padding: 0;
  margin-top: 5px;
}

.ota-log-box {
  background: #111118;
  border: 1px solid #3a3a48;
  border-radius: 8px;
  padding: 15px;
  margin: 10px 0;
  max-height: 300px;
  overflow-y: auto;
}

.ota-log-box pre {
  margin: 0;
  color: #8aff8a;
  font-size: 0.8rem;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Backups */
.backups-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.backup-item {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  border-radius: 8px;
  padding: 12px 15px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.backup-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.backup-name { font-weight: bold; color: #fff; font-size: 0.9rem; }
.backup-meta { color: #aaa; font-size: 0.8rem; }

.backup-actions { display: flex; gap: 8px; }

.btn-rollback {
  background: #ff9800;
  color: white;
  border: none;
  padding: 8px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
}

.btn-rollback:disabled { background: #555; color: #888; cursor: not-allowed; }

.btn-delete {
  background: transparent;
  border: 1px solid #555;
  color: #ff4d4d;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
}

.empty-state {
  text-align: center;
  padding: 20px;
  color: #aaa;
  font-style: italic;
  font-size: 0.9rem;
}

/* OTA status bar extra states */
.ota-status-bar.uploaded { border-left-color: #7c4dff; }
.ota-status-bar.validating { border-left-color: #ff9800; }
.ota-status-bar.applying { border-left-color: #ff9800; }
.ota-status-bar.success { border-left-color: #4caf50; }
.ota-status-bar.failed { border-left-color: #e53935; }

/* OTA da file card */
.card-desc {
  color: #aaa;
  font-size: 0.9rem;
  margin: -5px 0 15px 0;
}

.card-desc code {
  background: #1e1e26;
  padding: 1px 5px;
  border-radius: 4px;
  color: #ffd27b;
}

.file-upload-area {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.file-selected-name {
  color: #ccc;
  font-size: 0.9rem;
  background: #1e1e26;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid #3a3a48;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-upload {
  background: #00897b;
}

.staged-info {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #1a2a1a;
  border: 1px solid #2a5a2a;
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.staged-label {
  color: #aaa;
  font-size: 0.85rem;
}

.staged-name {
  color: #8aff8a;
  font-weight: bold;
  font-size: 0.9rem;
}

.staged-date {
  color: #aaa;
  font-size: 0.8rem;
  margin-left: auto;
}

.ota-apply-section {
  margin-bottom: 12px;
}

.apply-desc {
  color: #ccc;
  font-size: 0.9rem;
  margin: 0 0 10px 0;
}

.btn-apply {
  background: #4caf50;
}

.ota-success-box {
  background: #1a2a1a;
  border: 1px solid #4caf50;
  border-radius: 8px;
  padding: 10px 15px;
  color: #8aff8a;
  font-size: 0.9rem;
  margin-bottom: 12px;
}
</style>
