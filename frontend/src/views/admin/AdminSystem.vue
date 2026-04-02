<template>
  <div class="admin-system">

    <div class="header-section">
      <h2>Sistema ⚙️</h2>
      <p>Gestisci aggiornamenti, backup, rollback e alimentazione.</p>
    </div>

    <!-- Power controls -->
    <div class="card">
      <h3>Alimentazione 🔌</h3>
      <div class="power-row">
        <button class="btn-power standby" @click="sendAction('standby')">🌙 Standby</button>
        <button class="btn-power reboot" @click="sendAction('reboot')">🔄 Riavvia</button>
        <button class="btn-power shutdown" @click="sendAction('shutdown')">⏻ Spegni</button>
      </div>
    </div>

    <!-- OTA Update -->
    <div class="card">
      <h3>Aggiornamento OTA ⬆️</h3>

      <div class="ota-status-bar" :class="otaStatus.status">
        <span>Stato: <strong>{{ otaStatusLabel }}</strong></span>
        <span v-if="otaStatus.mode"> — Modalità: {{ otaStatus.mode }}</span>
        <span v-if="otaStatus.finished_at"> — Finito: {{ formatDate(otaStatus.finished_at) }}</span>
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
import { ref, computed, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

// Power
async function sendAction(azione) {
  const labels = { standby: 'mettere in standby', reboot: 'riavviare', shutdown: 'spegnere' }
  if (!confirm(`Vuoi davvero ${labels[azione]} la GufoBox?`)) return
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system', { azione }))
  } catch (e) {
    alert(extractApiError(e, `Errore: ${azione}`))
  }
}

// OTA
const otaStatus = ref({ status: 'idle', mode: null, started_at: null, finished_at: null, error: null })
const otaLog = ref('')
const showLog = ref(false)
const rollingBack = ref(false)

const otaRunning = computed(() => otaStatus.value.status === 'running')
const otaStatusLabel = computed(() => {
  const map = { idle: 'In attesa', running: 'In corso...', done: 'Completato ✅', error: 'Errore ❌' }
  return map[otaStatus.value.status] || otaStatus.value.status
})

async function loadOtaStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/system/ota/status'))
    otaStatus.value = data
  } catch (e) {
    console.error('Errore stato OTA:', extractApiError(e))
  }
}

async function startOta(mode) {
  if (!confirm(`Avviare aggiornamento in modalità "${mode}"?`)) return
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/ota/start', { mode }))
    setTimeout(loadOtaStatus, 2000)
  } catch (e) {
    alert(extractApiError(e, 'Errore avvio OTA'))
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
  try {
    const api = getApi()
    await api.delete(`/system/backups/${name}`)
    await loadBackups()
  } catch (e) {
    alert(extractApiError(e, 'Errore eliminazione backup'))
  }
}

async function rollback(backupName) {
  if (!confirm(`Ripristinare l'app dal backup "${backupName}"?\nI file correnti verranno sovrascritti.`)) return
  rollingBack.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/rollback', { backup_name: backupName }))
    alert('Rollback avviato! Riavvia la GufoBox per applicare le modifiche.')
  } catch (e) {
    alert(extractApiError(e, 'Errore rollback'))
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

onMounted(() => {
  loadOtaStatus()
  loadBackups()
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
</style>
