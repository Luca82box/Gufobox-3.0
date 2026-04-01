<template>
  <div class="admin-dashboard">
    
    <div class="dashboard-header">
      <h2>Stato del Sistema 📊</h2>
      <button class="btn-refresh" @click="fetchSystemInfo" :disabled="loading">
        {{ loading ? '🔄 Aggiornamento...' : '🔄 Aggiorna Ora' }}
      </button>
    </div>

    <div class="stats-grid" v-if="sysInfo">
      
      <div class="stat-card">
        <div class="stat-icon cpu-icon">⚙️</div>
        <div class="stat-details">
          <h3>CPU</h3>
          <p class="stat-value">{{ sysInfo.cpu_load || 0 }}%</p>
          <p class="stat-sub">Temp: {{ sysInfo.cpu_temp || 'N/D' }}°C</p>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon ram-icon">🧠</div>
        <div class="stat-details">
          <h3>Memoria RAM</h3>
          <p class="stat-value">{{ sysInfo.ram_used_mb || 0 }} / {{ sysInfo.ram_total_mb || 0 }} MB</p>
          <div class="mini-progress">
            <div class="mini-progress-fill" :style="{ width: (sysInfo.ram_percent || 0) + '%' }"></div>
          </div>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon disk-icon">💾</div>
        <div class="stat-details">
          <h3>Spazio di Archiviazione</h3>
          <p class="stat-value">{{ sysInfo.disk_used_gb || 0 }} / {{ sysInfo.disk_total_gb || 0 }} GB</p>
          <div class="mini-progress">
            <div class="mini-progress-fill disk-fill" :style="{ width: (sysInfo.disk_percent || 0) + '%' }"></div>
          </div>
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-icon time-icon">⏱️</div>
        <div class="stat-details">
          <h3>Tempo di Attività</h3>
          <p class="stat-value">{{ formatUptime(sysInfo.uptime_sec) }}</p>
          <p class="stat-sub">Batteria: {{ sysInfo.battery_percent || '100' }}% 🔋</p>
        </div>
      </div>

    </div>

    <div v-else-if="!loading" class="error-state">
      Impossibile caricare i dati di sistema.
    </div>

    <div class="system-actions">
      <h3>Controllo Alimentazione</h3>
      <div class="action-buttons">
        <button class="btn-power btn-reboot" @click="systemReboot">
          🔄 Riavvia GufoBox
        </button>
        <button class="btn-power btn-shutdown" @click="systemShutdown">
          ⏻ Spegni GufoBox
        </button>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useApi } from '../../composables/useApi'

const { guardedCall, getApi, extractApiError } = useApi()

const sysInfo = ref(null)
const loading = ref(false)
let pollingTimer = null

// 1. Caricamento Dati
async function fetchSystemInfo() {
  loading.value = true
  try {
    const api = getApi()
    // Chiamata fittizia: il backend Python dovrà esporre questo endpoint
    const { data } = await guardedCall(() => api.get('/system/info'))
    sysInfo.value = data
  } catch (e) {
    console.error('Errore lettura sistema:', extractApiError(e))
  } finally {
    loading.value = false
  }
}

// 2. Comandi di Alimentazione
async function systemReboot() {
  if (!confirm('Vuoi davvero riavviare la GufoBox? La riproduzione si fermerà.')) return
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/reboot'))
    alert('Riavvio in corso... La pagina si ricaricherà tra poco.')
    setTimeout(() => window.location.reload(), 15000)
  } catch (e) {
    alert(extractApiError(e, 'Errore comando riavvio'))
  }
}

async function systemShutdown() {
  if (!confirm('Vuoi spegnere definitivamente la GufoBox?')) return
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/shutdown'))
    alert('GufoBox in spegnimento. Puoi chiudere questa pagina.')
  } catch (e) {
    alert(extractApiError(e, 'Errore comando spegnimento'))
  }
}

// 3. Utility
function formatUptime(seconds) {
  if (!seconds) return '0h 0m'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

// 4. Ciclo di Vita
onMounted(() => {
  fetchSystemInfo()
  // Aggiorna le statistiche ogni 10 secondi
  pollingTimer = setInterval(fetchSystemInfo, 10000)
})

onBeforeUnmount(() => {
  if (pollingTimer) clearInterval(pollingTimer)
})
</script>

<style scoped>
.admin-dashboard {
  display: flex;
  flex-direction: column;
  gap: 30px;
}

.dashboard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 15px;
}

.dashboard-header h2 {
  margin: 0;
  color: #fff;
}

.btn-refresh {
  background: #3a3a48;
  color: white;
  border: none;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-refresh:hover:not(:disabled) {
  background: #4a4a5a;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 20px;
}

.stat-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 15px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.stat-icon {
  font-size: 2.5rem;
  width: 60px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1e1e26;
  border-radius: 12px;
}

.stat-details h3 {
  margin: 0 0 5px 0;
  font-size: 1rem;
  color: #aaa;
}

.stat-value {
  margin: 0;
  font-size: 1.4rem;
  font-weight: bold;
  color: #fff;
}

.stat-sub {
  margin: 5px 0 0 0;
  font-size: 0.85rem;
  color: #ffd27b;
}

.mini-progress {
  width: 100%;
  height: 6px;
  background: #1e1e26;
  border-radius: 3px;
  margin-top: 8px;
  overflow: hidden;
}

.mini-progress-fill {
  height: 100%;
  background: #4caf50;
  transition: width 0.5s ease;
}

.disk-fill { background: #3f51b5; }

.system-actions {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  border-left: 4px solid #ff9800;
}

.system-actions h3 {
  margin-top: 0;
  color: #fff;
}

.action-buttons {
  display: flex;
  gap: 15px;
  flex-wrap: wrap;
}

.btn-power {
  padding: 12px 20px;
  border: none;
  border-radius: 8px;
  font-size: 1.1rem;
  font-weight: bold;
  cursor: pointer;
  color: white;
  flex: 1;
  min-width: 200px;
  transition: opacity 0.2s;
}

.btn-power:hover { opacity: 0.8; }
.btn-reboot { background: #ff9800; }
.btn-shutdown { background: #ff4d4d; }

.error-state {
  text-align: center;
  padding: 40px;
  color: #ff4d4d;
  background: #2a2a35;
  border-radius: 12px;
}
</style>

