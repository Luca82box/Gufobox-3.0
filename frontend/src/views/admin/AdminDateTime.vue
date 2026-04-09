<template>
  <div class="admin-datetime">

    <div class="header-section">
      <h2>Data, Ora e Fuso Orario 🕐</h2>
      <p>Visualizza l'ora del dispositivo, lo stato NTP e configura il fuso orario.</p>
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- Orologio dispositivo -->
    <div class="card">
      <h3>🕐 Data e Ora Dispositivo</h3>
      <div class="datetime-display">
        <div class="clock-big">{{ deviceTime }}</div>
        <div class="date-big">{{ deviceDate }}</div>
        <div class="tz-badge">{{ deviceTimezone }}</div>
      </div>

      <div class="ntp-row">
        <div class="ntp-dot" :class="ntpSynced ? 'dot-ok' : 'dot-warn'"></div>
        <span class="ntp-label">
          NTP: <strong>{{ ntpSynced ? 'Sincronizzato ✅' : 'Non sincronizzato ⚠️' }}</strong>
        </span>
        <button class="btn-secondary" @click="forceNtpSync" :disabled="ntpBusy">
          {{ ntpBusy ? '⏳ Sync...' : '🔄 Forza Sincronizzazione' }}
        </button>
      </div>
    </div>

    <!-- Timezone selector -->
    <div class="card">
      <h3>🌍 Fuso Orario (Timezone)</h3>
      <p class="card-desc">Seleziona il fuso orario corretto per il tuo dispositivo. Richiede i permessi sudo.</p>

      <div class="tz-form">
        <div class="form-group">
          <label>Fuso orario</label>
          <select v-model="selectedTimezone" class="select-tz">
            <optgroup label="Europa">
              <option value="Europe/Rome">Europe/Rome (Roma, Milano)</option>
              <option value="Europe/London">Europe/London (Londra)</option>
              <option value="Europe/Paris">Europe/Paris (Parigi)</option>
              <option value="Europe/Berlin">Europe/Berlin (Berlino)</option>
              <option value="Europe/Madrid">Europe/Madrid (Madrid)</option>
              <option value="Europe/Amsterdam">Europe/Amsterdam</option>
              <option value="Europe/Zurich">Europe/Zurich (Zurigo)</option>
              <option value="Europe/Athens">Europe/Athens (Atene)</option>
              <option value="Europe/Warsaw">Europe/Warsaw (Varsavia)</option>
              <option value="Europe/Moscow">Europe/Moscow (Mosca)</option>
            </optgroup>
            <optgroup label="America">
              <option value="America/New_York">America/New_York (Est USA)</option>
              <option value="America/Chicago">America/Chicago (Centro USA)</option>
              <option value="America/Denver">America/Denver (Montagna USA)</option>
              <option value="America/Los_Angeles">America/Los_Angeles (Ovest USA)</option>
              <option value="America/Sao_Paulo">America/Sao_Paulo (Brasile)</option>
            </optgroup>
            <optgroup label="Asia / Pacifico">
              <option value="Asia/Tokyo">Asia/Tokyo (Giappone)</option>
              <option value="Asia/Shanghai">Asia/Shanghai (Cina)</option>
              <option value="Asia/Kolkata">Asia/Kolkata (India)</option>
              <option value="Asia/Dubai">Asia/Dubai</option>
              <option value="Australia/Sydney">Australia/Sydney</option>
            </optgroup>
            <optgroup label="Altro">
              <option value="UTC">UTC</option>
            </optgroup>
          </select>
        </div>

        <button class="btn-primary" @click="setTimezone" :disabled="tzBusy">
          {{ tzBusy ? '⏳ Applicazione...' : '💾 Applica Timezone' }}
        </button>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

const deviceTime = ref('--:--:--')
const deviceDate = ref('----/--/--')
const deviceTimezone = ref('UTC')
const ntpSynced = ref(false)
const ntpBusy = ref(false)
const tzBusy = ref(false)
const selectedTimezone = ref('Europe/Rome')

let refreshInterval = null

async function loadDatetimeStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/system/datetime'))
    deviceTime.value = data.time || '--:--:--'
    deviceDate.value = data.date || '----/--/--'
    deviceTimezone.value = data.timezone || 'UTC'
    ntpSynced.value = data.ntp?.synchronized || false
    if (data.timezone) selectedTimezone.value = data.timezone
  } catch (_) {}
}

async function forceNtpSync() {
  ntpBusy.value = true
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/ntp/sync'))
    showSuccess('Sincronizzazione NTP avviata ✅')
    setTimeout(loadDatetimeStatus, 3000)
  } catch (e) {
    showError(extractApiError(e, 'Errore sincronizzazione NTP'))
  } finally {
    ntpBusy.value = false
  }
}

async function setTimezone() {
  if (!selectedTimezone.value) return
  tzBusy.value = true
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/system/timezone', { timezone: selectedTimezone.value }))
    showSuccess(`Timezone impostato: ${selectedTimezone.value} ✅`)
    await loadDatetimeStatus()
  } catch (e) {
    showError(extractApiError(e, 'Errore impostazione timezone'))
  } finally {
    tzBusy.value = false
  }
}

onMounted(() => {
  loadDatetimeStatus()
  refreshInterval = setInterval(loadDatetimeStatus, 10000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<style scoped>
.admin-datetime { max-width: 680px; }

.header-section { margin-bottom: 24px; }
.header-section h2 { font-size: 1.6rem; font-weight: 700; color: #ffd27b; margin: 0 0 6px; }
.header-section p { color: #aaa; margin: 0; }

.card { background: #1e1e2e; border: 1px solid #2d2d3d; border-radius: 14px; padding: 22px; margin-bottom: 20px; }
.card h3 { font-size: 1.1rem; font-weight: 700; color: #fff; margin: 0 0 16px; }
.card-desc { color: #888; font-size: 0.88rem; margin: -8px 0 14px; }

.banner {
  padding: 12px 16px; border-radius: 10px; display: flex;
  justify-content: space-between; align-items: center; margin-bottom: 16px; font-size: 0.95rem;
}
.banner-success { background: rgba(76,175,80,0.15); border: 1px solid #4caf50; color: #81c784; }
.banner-error   { background: rgba(244,67,54,0.15); border: 1px solid #f44336; color: #e57373; }
.banner-close { background: none; border: none; color: inherit; cursor: pointer; font-size: 1rem; }

.datetime-display { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 16px 0; }
.clock-big { font-size: 3rem; font-weight: 800; color: #ffd27b; font-variant-numeric: tabular-nums; letter-spacing: 2px; }
.date-big { font-size: 1.1rem; color: #ccc; font-weight: 600; }
.tz-badge {
  background: rgba(63,81,181,0.25); border: 1px solid rgba(63,81,181,0.5);
  border-radius: 20px; color: #9fa8da; font-size: 0.82rem; padding: 3px 12px; margin-top: 4px;
}

.ntp-row { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.ntp-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dot-ok   { background: #4caf50; box-shadow: 0 0 6px #4caf50; }
.dot-warn { background: #ff9800; box-shadow: 0 0 6px #ff9800; }
.ntp-label { font-size: 0.9rem; color: #ccc; flex: 1; }

.tz-form { display: flex; flex-direction: column; gap: 14px; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: 0.85rem; color: #aaa; font-weight: 600; }
.select-tz {
  background: #252535; border: 1px solid #3a3a50; border-radius: 9px;
  color: #fff; font-size: 0.95rem; padding: 10px 12px; width: 100%; cursor: pointer;
}
.select-tz:focus { outline: none; border-color: #3f51b5; }
.select-tz option { background: #1e1e2e; }

.btn-primary {
  background: #3f51b5; border: none; border-radius: 9px; color: #fff;
  font-size: 0.95rem; font-weight: 700; padding: 10px 22px; cursor: pointer;
  transition: background 0.2s; align-self: flex-start;
}
.btn-primary:hover:not(:disabled) { background: #5c6bc0; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
  border-radius: 9px; color: #aaa; font-size: 0.85rem; padding: 8px 16px;
  cursor: pointer; transition: background 0.2s; white-space: nowrap;
}
.btn-secondary:hover:not(:disabled) { background: rgba(255,255,255,0.15); color: #fff; }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
