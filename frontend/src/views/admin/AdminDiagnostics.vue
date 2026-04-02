<template>
  <div class="admin-diagnostics">

    <div class="header-section">
      <h2>Diagnostica 🔬</h2>
      <p>Riepilogo dello stato del sistema, event log operativo e strumenti di verifica.</p>
    </div>

    <!-- Summary -->
    <div class="card">
      <div class="card-header">
        <h3>Riepilogo Sistema</h3>
        <button class="btn-refresh" @click="loadSummary" :disabled="loadingSummary">
          {{ loadingSummary ? '⏳' : '🔄' }}
        </button>
      </div>

      <div v-if="loadingSummary" class="loading-text">Caricamento... ⏳</div>

      <div v-else-if="summary" class="summary-body">
        <div class="summary-status" :class="summary.ok ? 'status-ok' : 'status-warn'">
          {{ summary.ok ? '✅ Sistema OK' : '⚠️ Attenzione: ci sono avvisi' }}
        </div>

        <div class="summary-grid">
          <div class="summary-item">
            <span class="item-label">Versione API</span>
            <span class="item-value">{{ summary.api_version || '—' }}</span>
          </div>
          <div class="summary-item">
            <span class="item-label">IP</span>
            <span class="item-value">{{ summary.ip || '—' }}</span>
          </div>
          <div class="summary-item">
            <span class="item-label">CPU Temp</span>
            <span class="item-value" :class="tempClass(summary.cpu_temp_celsius)">
              {{ summary.cpu_temp_celsius != null ? summary.cpu_temp_celsius + '°C' : 'N/D' }}
            </span>
          </div>
          <div class="summary-item">
            <span class="item-label">RAM</span>
            <span class="item-value" :class="percentClass(summary.ram_percent)">
              {{ summary.ram_percent != null ? summary.ram_percent + '%' : 'N/D' }}
            </span>
          </div>
          <div class="summary-item">
            <span class="item-label">Disco</span>
            <span class="item-value" :class="percentClass(summary.disk_percent)">
              {{ summary.disk_percent != null ? summary.disk_percent + '%' : 'N/D' }}
            </span>
          </div>
          <div class="summary-item">
            <span class="item-label">Uptime</span>
            <span class="item-value">{{ formatUptime(summary.uptime_seconds) }}</span>
          </div>
          <div class="summary-item">
            <span class="item-label">Player</span>
            <span class="item-value">
              {{ summary.player_running ? ('▶ ' + (summary.player_mode || 'running')) : '⏹ Fermo' }}
            </span>
          </div>
          <div class="summary-item">
            <span class="item-label">Standby</span>
            <span class="item-value">{{ summary.in_standby ? '🌙 Sì' : 'No' }}</span>
          </div>
          <div class="summary-item">
            <span class="item-label">OTA</span>
            <span class="item-value" :class="summary.ota_running ? 'text-warn' : ''">
              {{ summary.ota_running ? '⬆️ In corso' : (summary.ota_status || 'idle') }}
            </span>
          </div>
          <div class="summary-item">
            <span class="item-label">Backup</span>
            <span class="item-value">{{ summary.backup_count ?? '—' }}</span>
          </div>
          <div class="summary-item">
            <span class="item-label">Job attivi</span>
            <span class="item-value" :class="summary.active_jobs > 0 ? 'text-warn' : ''">
              {{ summary.active_jobs ?? 0 }}
            </span>
          </div>
          <div class="summary-item">
            <span class="item-label">Sveglie</span>
            <span class="item-value">{{ summary.alarm_count ?? 0 }}</span>
          </div>
        </div>

        <div v-if="summary.warnings && summary.warnings.length > 0" class="warnings-box">
          <h4>⚠️ Avvisi</h4>
          <ul>
            <li v-for="w in summary.warnings" :key="w">{{ w }}</li>
          </ul>
        </div>
      </div>

      <div v-else class="empty-state">
        Impossibile caricare il riepilogo.
      </div>
    </div>

    <!-- Self-check -->
    <div class="card">
      <div class="card-header">
        <h3>Self-Check Operativo</h3>
        <div class="header-actions">
          <button class="btn-action btn-selfcheck" @click="runSelfCheck" :disabled="loadingSelfcheck">
            {{ loadingSelfcheck ? '⏳ In corso...' : '🩺 Esegui Self-Check' }}
          </button>
        </div>
      </div>

      <div v-if="loadingSelfcheck" class="loading-text">Self-check in corso... ⏳</div>

      <div v-else-if="selfcheck" class="selfcheck-body">
        <div class="summary-status" :class="selfcheck.ok ? 'status-ok' : 'status-warn'">
          {{ selfcheck.ok ? '✅ Tutti i controlli OK' : '⚠️ Rilevati problemi' }}
        </div>

        <div v-if="selfcheck.errors && selfcheck.errors.length > 0" class="warnings-box error-box">
          <h4>❌ Errori ({{ selfcheck.errors.length }})</h4>
          <ul>
            <li v-for="e in selfcheck.errors" :key="e">{{ e }}</li>
          </ul>
        </div>

        <div v-if="selfcheck.warnings && selfcheck.warnings.length > 0" class="warnings-box">
          <h4>⚠️ Avvisi ({{ selfcheck.warnings.length }})</h4>
          <ul>
            <li v-for="w in selfcheck.warnings" :key="w">{{ w }}</li>
          </ul>
        </div>

        <div class="checks-grid">
          <div
            v-for="check in selfcheck.checks"
            :key="check.name"
            class="check-item"
            :class="check.ok ? 'check-ok' : 'check-fail'"
            :title="check.note || ''"
          >
            <span class="check-icon">{{ check.ok ? '✅' : '❌' }}</span>
            <span class="check-name">{{ check.name }}</span>
            <span v-if="check.note && !check.ok" class="check-note">{{ check.note }}</span>
          </div>
        </div>

        <div class="selfcheck-note">{{ selfcheck.note }}</div>
        <div v-if="selfcheck.timestamp" class="selfcheck-ts">
          Eseguito: {{ formatTs(selfcheck.timestamp) }}
        </div>
      </div>

      <div v-else class="empty-state">
        Premi "Esegui Self-Check" per avviare il controllo operativo.
      </div>
    </div>

    <!-- Event log -->
    <div class="card">
      <div class="card-header">
        <h3>Event Log Operativo</h3>
        <button class="btn-refresh" @click="loadEvents" :disabled="loadingEvents">
          {{ loadingEvents ? '⏳' : '🔄' }}
        </button>
      </div>

      <div v-if="loadingEvents" class="loading-text">Caricamento eventi... ⏳</div>

      <div v-else-if="events && events.length > 0" class="events-body">
        <table class="events-table">
          <thead>
            <tr>
              <th>Orario</th>
              <th>Area</th>
              <th>Severità</th>
              <th>Messaggio</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ev in events"
              :key="ev.ts + ev.message"
              :class="'ev-row ev-' + ev.severity"
            >
              <td class="ev-ts">{{ formatTs(ev.ts) }}</td>
              <td class="ev-area">{{ ev.area }}</td>
              <td class="ev-severity">
                <span :class="'badge badge-' + ev.severity">{{ ev.severity }}</span>
              </td>
              <td class="ev-msg">
                {{ ev.message }}
                <span v-if="ev.details" class="ev-details" :title="JSON.stringify(ev.details)">ℹ️</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else-if="!loadingEvents" class="empty-state">
        Nessun evento registrato.
      </div>
    </div>

    <!-- Tools check -->
    <div class="card">
      <div class="card-header">
        <h3>Strumenti di Sistema</h3>
        <div class="header-actions">
          <button class="btn-action btn-export" @click="exportDiag" :disabled="loadingExport">
            {{ loadingExport ? '⏳' : '📥 Esporta Diagnostica' }}
          </button>
          <button class="btn-refresh" @click="loadTools" :disabled="loadingTools">
            {{ loadingTools ? '⏳' : '🔄' }}
          </button>
        </div>
      </div>

      <div v-if="loadingTools" class="loading-text">Verifica in corso... ⏳</div>

      <div v-else-if="tools" class="tools-body">
        <div class="tools-overall" :class="tools.all_critical_ok ? 'status-ok' : 'status-error'">
          {{ tools.all_critical_ok ? '✅ Tutti i tool critici OK' : '❌ Mancano tool critici' }}
        </div>

        <div class="tools-grid">
          <div
            v-for="(available, name) in tools.tools"
            :key="name"
            class="tool-item"
            :class="available ? 'tool-ok' : 'tool-missing'"
          >
            <span class="tool-icon">{{ available ? '✅' : '❌' }}</span>
            <span class="tool-name">{{ name }}</span>
          </div>
        </div>
      </div>

      <div v-else class="empty-state">
        Impossibile caricare i tool.
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

const summary = ref(null)
const tools = ref(null)
const selfcheck = ref(null)
const events = ref([])
const loadingSummary = ref(false)
const loadingTools = ref(false)
const loadingSelfcheck = ref(false)
const loadingEvents = ref(false)
const loadingExport = ref(false)

async function loadSummary() {
  loadingSummary.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/diag/summary'))
    summary.value = data
  } catch (e) {
    console.error('Errore diag/summary:', extractApiError(e))
  } finally {
    loadingSummary.value = false
  }
}

async function loadTools() {
  loadingTools.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/diag/tools'))
    tools.value = data
  } catch (e) {
    console.error('Errore diag/tools:', extractApiError(e))
  } finally {
    loadingTools.value = false
  }
}

async function loadEvents() {
  loadingEvents.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/diag/events?limit=100'))
    events.value = data.events || []
  } catch (e) {
    console.error('Errore diag/events:', extractApiError(e))
  } finally {
    loadingEvents.value = false
  }
}

async function runSelfCheck() {
  loadingSelfcheck.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/diag/selfcheck'))
    selfcheck.value = data
    // Refresh events after selfcheck to show the logged event
    await loadEvents()
  } catch (e) {
    console.error('Errore diag/selfcheck:', extractApiError(e))
  } finally {
    loadingSelfcheck.value = false
  }
}

async function exportDiag() {
  loadingExport.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/diag/export'))
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `gufobox-diag-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('Errore diag/export:', extractApiError(e))
  } finally {
    loadingExport.value = false
  }
}

function formatUptime(seconds) {
  if (!seconds) return '0h 0m'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

function formatTs(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'medium' })
  } catch {
    return ts
  }
}

function tempClass(val) {
  if (val == null) return ''
  if (val > 75) return 'text-error'
  if (val > 60) return 'text-warn'
  return 'text-ok'
}

function percentClass(val) {
  if (val == null) return ''
  if (val > 90) return 'text-error'
  if (val > 75) return 'text-warn'
  return ''
}

onMounted(() => {
  loadSummary()
  loadTools()
  loadEvents()
})
</script>

<style scoped>
.admin-diagnostics {
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

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
  margin-bottom: 15px;
  flex-wrap: wrap;
  gap: 8px;
}

.card-header h3 { margin: 0; color: #ffd27b; }

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.btn-refresh {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
}

.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-action {
  border: none;
  padding: 7px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: bold;
  transition: opacity 0.2s;
}

.btn-action:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-selfcheck { background: #5b6af0; color: #fff; }
.btn-selfcheck:hover:not(:disabled) { background: #4a58d8; }

.btn-export { background: #2e7d32; color: #fff; }
.btn-export:hover:not(:disabled) { background: #1b5e20; }

.loading-text { color: #aaa; font-style: italic; text-align: center; padding: 20px 0; }

/* Summary status */
.summary-status {
  padding: 10px 16px;
  border-radius: 8px;
  font-weight: bold;
  margin-bottom: 15px;
}

.status-ok { background: #1a2e1a; color: #4caf50; border: 1px solid #4caf50; }
.status-warn { background: #2e2210; color: #ff9800; border: 1px solid #ff9800; }
.status-error { background: #2e1010; color: #ff4d4d; border: 1px solid #ff4d4d; }

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
}

.summary-item {
  background: #1e1e26;
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.item-label { font-size: 0.75rem; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; }
.item-value { font-size: 0.95rem; font-weight: bold; color: #fff; }

.text-ok { color: #4caf50; }
.text-warn { color: #ff9800; }
.text-error { color: #ff4d4d; }

.warnings-box {
  background: #2a1e14;
  border: 1px solid #ff9800;
  border-radius: 8px;
  padding: 14px 18px;
  color: #ffd27b;
  margin-top: 15px;
}

.warnings-box h4 { margin: 0 0 8px 0; }
.warnings-box ul { margin: 0; padding-left: 18px; }
.warnings-box li { margin-bottom: 3px; font-size: 0.9rem; }

.error-box {
  background: #2a1414;
  border-color: #ff4d4d;
  color: #ff9090;
}

/* Self-check */
.checks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.check-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  background: #1e1e26;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 0.88rem;
}

.check-ok { border-left: 3px solid #4caf50; }
.check-fail { border-left: 3px solid #ff4d4d; }

.check-icon { font-size: 0.85rem; }
.check-name { color: #fff; font-weight: bold; }
.check-note { color: #ff9090; font-size: 0.8rem; }

.selfcheck-note {
  margin-top: 12px;
  font-size: 0.85rem;
  color: #aaa;
  font-style: italic;
}

.selfcheck-ts {
  font-size: 0.8rem;
  color: #666;
  margin-top: 4px;
}

/* Events table */
.events-body { overflow-x: auto; }

.events-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}

.events-table th {
  background: #1a1a24;
  color: #aaa;
  padding: 8px 12px;
  text-align: left;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid #3a3a48;
}

.events-table td {
  padding: 7px 12px;
  border-bottom: 1px solid #2a2a38;
  color: #ddd;
  vertical-align: top;
}

.ev-row:hover td { background: #1e1e2a; }

.ev-ts { white-space: nowrap; color: #888; font-size: 0.82rem; }
.ev-area { white-space: nowrap; font-weight: bold; color: #bbb; }
.ev-msg { word-break: break-word; }

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: bold;
  text-transform: uppercase;
}

.badge-info    { background: #1a2e3a; color: #64b5f6; border: 1px solid #64b5f6; }
.badge-warning { background: #2a1e0a; color: #ffb74d; border: 1px solid #ffb74d; }
.badge-error   { background: #2a0a0a; color: #ef5350; border: 1px solid #ef5350; }

.ev-info td    { border-left: 3px solid #64b5f6; }
.ev-warning td { border-left: 3px solid #ffb74d; }
.ev-error td   { border-left: 3px solid #ef5350; }

.ev-details {
  margin-left: 4px;
  cursor: help;
  font-size: 0.85rem;
}

/* Tools */
.tools-overall {
  padding: 10px 16px;
  border-radius: 8px;
  font-weight: bold;
  margin-bottom: 15px;
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px;
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #1e1e26;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 0.9rem;
}

.tool-ok { border-left: 3px solid #4caf50; }
.tool-missing { border-left: 3px solid #ff4d4d; }
.tool-icon { font-size: 0.9rem; }
.tool-name { color: #fff; }

.empty-state {
  text-align: center;
  padding: 20px;
  color: #aaa;
  font-style: italic;
}
</style>
