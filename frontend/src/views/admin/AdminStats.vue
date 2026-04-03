<template>
  <div class="admin-stats">
    <div class="header-section">
      <h2>🦉 Statistiche del Gufetto 📊</h2>
      <p>Scopri quanto tempo il tuo bambino passa ad ascoltare storie e musica con il Gufetto!</p>
    </div>

    <!-- ASCOLTO GIORNALIERO (7 giorni) -->
    <div class="stats-card">
      <h3>📅 Ascolto Ultimi 7 Giorni</h3>
      <div v-if="loading.daily" class="loading-state">🦉 Il Gufetto sta contando... ⏳</div>
      <div v-else-if="dailyStats.length === 0" class="empty-state">
        🥚 Ancora nessun dato! Metti una statuina e inizia ad ascoltare!
      </div>
      <div v-else>
        <div class="week-total">
          Totale settimana: <strong>{{ weeklyTotal }} min</strong>
          ({{ Math.floor(weeklyTotal / 60) }}h {{ weeklyTotal % 60 }}min 🦉)
        </div>
        <div class="chart-container">
          <div class="bar-chart">
            <div
              v-for="stat in dailyStats"
              :key="stat.date"
              class="bar-wrapper"
            >
              <div class="bar-value">{{ stat.minutes }}m</div>
              <div class="bar owl-bar" :style="{ height: getBarHeight(stat.minutes, maxDailyMin) + '%' }"></div>
              <div class="bar-label">{{ formatDate(stat.date) }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- STATUINE PIÙ USATE -->
    <div class="stats-card">
      <h3>🏆 Statuine Più Amate</h3>
      <div v-if="loading.figurines" class="loading-state">🦉 Il Gufetto sta cercando le statuine... ⏳</div>
      <div v-else-if="topFigurines.length === 0" class="empty-state">
        🎭 Nessuna statuina usata ancora! Prova a mettere una statuina sul Gufetto!
      </div>
      <div v-else class="figurines-list">
        <div
          v-for="(fig, idx) in topFigurines"
          :key="fig.rfid_uid"
          class="figurine-row"
        >
          <span class="rank-badge">{{ rankEmoji(idx) }}</span>
          <div class="figurine-info">
            <span class="figurine-uid">{{ fig.rfid_uid }}</span>
            <span class="figurine-sessions">{{ fig.sessions }} sessioni</span>
          </div>
          <div class="figurine-bar-wrap">
            <div
              class="figurine-bar"
              :style="{ width: getFigurineBarWidth(fig.minutes) + '%' }"
            ></div>
          </div>
          <span class="figurine-minutes">{{ fig.minutes }} min</span>
        </div>
      </div>
    </div>

    <!-- ORARI DI UTILIZZO -->
    <div class="stats-card">
      <h3>🕐 Orari di Utilizzo</h3>
      <p class="card-subtitle">In quali ore il Gufetto viene usato di più?</p>
      <div v-if="loading.hourly" class="loading-state">🦉 Il Gufetto sta guardando l'orologio... ⏳</div>
      <div v-else-if="hourlyStats.every(h => h.minutes === 0)" class="empty-state">
        🌙 Ancora nessun dato sugli orari! Ascolta qualcosa con il Gufetto!
      </div>
      <div v-else class="chart-container hourly-chart">
        <div class="bar-chart hourly-bar-chart">
          <div
            v-for="stat in hourlyStats"
            :key="stat.hour"
            class="bar-wrapper hourly-wrapper"
            :title="`${stat.hour}:00 — ${stat.minutes} min`"
          >
            <div
              class="bar hourly-bar"
              :style="{ height: getBarHeight(stat.minutes, maxHourlyMin) + '%' }"
              :class="getTimeClass(stat.hour)"
            ></div>
            <div class="bar-label hour-label" v-if="stat.hour % 3 === 0">{{ stat.hour }}h</div>
            <div class="bar-label hour-label" v-else></div>
          </div>
        </div>
        <div class="time-legend">
          <span class="legend-item">🌅 Mattina</span>
          <span class="legend-item">☀️ Pomeriggio</span>
          <span class="legend-item">🌙 Sera</span>
        </div>
      </div>
    </div>

    <!-- STORICO BATTERIA -->
    <div class="stats-card">
      <h3>🔋 Storico Batteria</h3>
      <div class="hours-selector">
        <button
          v-for="h in [6, 12, 24, 48]"
          :key="h"
          @click="batteryHours = h; loadBatteryHistory()"
          :class="{ active: batteryHours === h }"
          class="hours-btn"
        >{{ h }}h</button>
      </div>
      <div v-if="loading.battery" class="loading-state">🦉 Il Gufetto sta leggendo la batteria... ⏳</div>
      <div v-else-if="batteryHistory.length === 0" class="empty-state">
        🪫 Nessun dato batteria disponibile ancora.
      </div>
      <div v-else class="battery-chart-container">
        <svg class="battery-svg" viewBox="0 0 600 150" preserveAspectRatio="none">
          <!-- Linee di riferimento -->
          <line x1="0" y1="30" x2="600" y2="30" stroke="#333" stroke-width="1" stroke-dasharray="4"/>
          <text x="2" y="28" fill="#666" font-size="10">100%</text>
          <line x1="0" y1="75" x2="600" y2="75" stroke="#333" stroke-width="1" stroke-dasharray="4"/>
          <text x="2" y="73" fill="#666" font-size="10">50%</text>
          <line x1="0" y1="120" x2="600" y2="120" stroke="#f44" stroke-width="1" stroke-dasharray="4"/>
          <text x="2" y="118" fill="#f44" font-size="10">20%</text>
          <!-- Curva della batteria -->
          <polyline
            :points="batteryPolyline"
            fill="none"
            stroke="#4caf50"
            stroke-width="2.5"
            stroke-linejoin="round"
          />
          <!-- Indicatori ricarica -->
          <circle
            v-for="(pt, i) in chargingPoints"
            :key="i"
            :cx="pt.x"
            :cy="pt.y"
            r="3"
            fill="#ffd27b"
          />
        </svg>
        <div class="battery-legend">
          <span><svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#4caf50" stroke-width="2.5"/></svg> Batteria %</span>
          <span>🟡 In ricarica</span>
        </div>
      </div>
    </div>

    <!-- ESPORTA DATI -->
    <div class="stats-card export-card">
      <h3>📤 Esporta Dati</h3>
      <p class="card-subtitle">Scarica le statistiche del Gufetto nel formato che preferisci!</p>
      <div class="export-buttons">
        <button class="btn-export btn-json" @click="exportData('json')" :disabled="exporting !== null">
          {{ exporting === 'json' ? '⏳ Esporto...' : '📋 Esporta JSON' }}
        </button>
        <button class="btn-export btn-csv" @click="exportData('csv')" :disabled="exporting !== null">
          {{ exporting === 'csv' ? '⏳ Esporto...' : '📊 Esporta CSV' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall } = useApi()

const loading = ref({ daily: true, figurines: true, hourly: true, battery: false })
const dailyStats = ref([])
const topFigurines = ref([])
const hourlyStats = ref([])
const batteryHistory = ref([])
const batteryHours = ref(24)
const exporting = ref(null)

// ---- Calcolatori ----
const maxDailyMin = computed(() => Math.max(...dailyStats.value.map(s => s.minutes), 60))
const maxHourlyMin = computed(() => Math.max(...hourlyStats.value.map(s => s.minutes), 1))
const maxFigurineMin = computed(() => Math.max(...topFigurines.value.map(f => f.minutes), 1))
const weeklyTotal = computed(() => dailyStats.value.reduce((acc, s) => acc + s.minutes, 0))

// ---- Caricamento dati ----
async function loadDailyStats() {
  loading.value.daily = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/stats/daily'))
    dailyStats.value = (data || []).reverse()
  } catch (e) {
    console.error('Errore caricamento stats giornaliere:', e)
  } finally {
    loading.value.daily = false
  }
}

async function loadTopFigurines() {
  loading.value.figurines = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/stats/top-figurines?n=5'))
    topFigurines.value = data || []
  } catch (e) {
    console.error('Errore caricamento statuine top:', e)
  } finally {
    loading.value.figurines = false
  }
}

async function loadHourlyStats() {
  loading.value.hourly = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/stats/hourly'))
    hourlyStats.value = data || []
  } catch (e) {
    console.error('Errore caricamento stats orarie:', e)
  } finally {
    loading.value.hourly = false
  }
}

async function loadBatteryHistory() {
  loading.value.battery = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get(`/stats/battery-history?hours=${batteryHours.value}`))
    batteryHistory.value = data || []
  } catch (e) {
    console.error('Errore caricamento storico batteria:', e)
  } finally {
    loading.value.battery = false
  }
}

// ---- Grafico batteria (SVG) ----
const batteryPolyline = computed(() => {
  const pts = batteryHistory.value
  if (pts.length < 2) return ''
  const minTs = pts[0].ts
  const maxTs = pts[pts.length - 1].ts
  const tsRange = Math.max(maxTs - minTs, 1)
  return pts.map(pt => {
    const x = ((pt.ts - minTs) / tsRange) * 596 + 2
    const y = 30 + (1 - pt.percent / 100) * 105
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})

const chargingPoints = computed(() => {
  const pts = batteryHistory.value
  if (pts.length < 2) return []
  const minTs = pts[0].ts
  const maxTs = pts[pts.length - 1].ts
  const tsRange = Math.max(maxTs - minTs, 1)
  return pts
    .filter(pt => pt.charging)
    .map(pt => ({
      x: ((pt.ts - minTs) / tsRange) * 596 + 2,
      y: 30 + (1 - pt.percent / 100) * 105,
    }))
})

// ---- Export ----
async function exportData(format) {
  exporting.value = format
  try {
    const api = getApi()
    if (format === 'csv') {
      const resp = await api.get('/stats/export?format=csv', { responseType: 'blob' })
      const url = URL.createObjectURL(resp.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'gufobox_stats.csv'
      a.click()
      URL.revokeObjectURL(url)
    } else {
      const { data } = await guardedCall(() => api.get('/stats/export?format=json'))
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'gufobox_stats.json'
      a.click()
      URL.revokeObjectURL(url)
    }
  } catch (e) {
    console.error('Errore export:', e)
  } finally {
    exporting.value = null
  }
}

// ---- Utility ----
function getBarHeight(value, max) {
  if (!max) return 0
  return Math.max((value / max) * 100, value > 0 ? 3 : 0)
}

function getFigurineBarWidth(minutes) {
  return Math.max((minutes / maxFigurineMin.value) * 100, minutes > 0 ? 3 : 0)
}

function formatDate(dateStr) {
  const date = new Date(dateStr)
  return date.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
}

function rankEmoji(idx) {
  return ['🥇', '🥈', '🥉', '4️⃣', '5️⃣'][idx] || `${idx + 1}.`
}

function getTimeClass(hour) {
  if (hour >= 6 && hour < 13) return 'morning'
  if (hour >= 13 && hour < 20) return 'afternoon'
  return 'evening'
}

onMounted(() => {
  loadDailyStats()
  loadTopFigurines()
  loadHourlyStats()
  loadBatteryHistory()
})
</script>

<style scoped>
.admin-stats { display: flex; flex-direction: column; gap: 24px; }

.header-section h2 { margin: 0; color: #ffd27b; font-size: 1.6rem; }
.header-section p { color: #aaa; margin: 6px 0 0 0; }

/* Cards */
.stats-card {
  background: #2a2a35;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 4px 14px rgba(0,0,0,0.25);
  border: 1px solid #3a3a4a;
}
.stats-card h3 {
  margin-top: 0;
  color: #ffd27b;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 12px;
  margin-bottom: 16px;
  font-size: 1.15rem;
}
.card-subtitle { color: #aaa; margin: -10px 0 16px 0; font-size: 0.9rem; }

/* Loading / Empty */
.loading-state { text-align: center; color: #aaa; padding: 30px 0; font-size: 1.05rem; }
.empty-state { text-align: center; color: #aaa; padding: 30px 0; font-style: italic; }

/* Totale settimana */
.week-total { color: #ccc; font-size: 0.95rem; margin-bottom: 12px; }
.week-total strong { color: #ffd27b; }

/* Grafici a barre */
.chart-container { height: 220px; padding-bottom: 20px; }
.bar-chart {
  display: flex;
  justify-content: space-around;
  align-items: flex-end;
  height: 100%;
  border-bottom: 2px solid #3a3a48;
}
.bar-wrapper {
  display: flex; flex-direction: column;
  align-items: center; justify-content: flex-end;
  height: 100%; flex: 1; gap: 6px;
}
.bar {
  width: 36px;
  background: linear-gradient(180deg, #ffd27b 0%, #ff8c42 100%);
  border-radius: 6px 6px 0 0;
  min-height: 3px;
  transition: height 0.5s ease-out;
}
.owl-bar { background: linear-gradient(180deg, #ffd27b 0%, #ff8c42 100%); }
.bar-value { color: #ffd27b; font-size: 0.85rem; font-weight: bold; }
.bar-label { color: #888; font-size: 0.8rem; margin-top: 8px; }

/* Statuine */
.figurines-list { display: flex; flex-direction: column; gap: 12px; }
.figurine-row {
  display: flex; align-items: center; gap: 12px;
  background: #222230; border-radius: 10px; padding: 10px 14px;
}
.rank-badge { font-size: 1.4rem; min-width: 2rem; text-align: center; }
.figurine-info { flex: 0 0 140px; }
.figurine-uid { display: block; color: #fff; font-weight: bold; font-size: 0.9rem; word-break: break-all; }
.figurine-sessions { color: #888; font-size: 0.8rem; }
.figurine-bar-wrap { flex: 1; background: #1a1a25; border-radius: 6px; height: 12px; overflow: hidden; }
.figurine-bar {
  height: 100%;
  background: linear-gradient(90deg, #ffd27b, #ff8c42);
  border-radius: 6px;
  transition: width 0.5s ease-out;
}
.figurine-minutes { color: #ffd27b; font-weight: bold; font-size: 0.9rem; min-width: 55px; text-align: right; }

/* Orari */
.hourly-chart { height: 180px; }
.hourly-bar-chart { gap: 0; }
.hourly-wrapper { flex: 1; min-width: 0; }
.hourly-bar {
  width: 100%;
  min-height: 2px;
  border-radius: 3px 3px 0 0;
  transition: height 0.4s ease-out;
}
.hourly-bar.morning { background: linear-gradient(180deg, #ffca28, #ffa000); }
.hourly-bar.afternoon { background: linear-gradient(180deg, #4caf50, #2e7d32); }
.hourly-bar.evening { background: linear-gradient(180deg, #7c4dff, #3f51b5); }
.hour-label { font-size: 0.7rem; color: #666; }

.time-legend {
  display: flex; justify-content: center; gap: 20px;
  margin-top: 10px; font-size: 0.85rem;
}
.legend-item { color: #aaa; }

/* Batteria */
.hours-selector { display: flex; gap: 8px; margin-bottom: 14px; }
.hours-btn {
  background: #222230; border: 1px solid #3a3a48; color: #aaa;
  padding: 5px 14px; border-radius: 8px; cursor: pointer; font-size: 0.9rem;
  transition: all 0.2s;
}
.hours-btn:hover { background: #2e2e40; color: #fff; }
.hours-btn.active { background: #ffd27b; color: #1a1a2a; border-color: #ffd27b; font-weight: bold; }

.battery-chart-container { overflow: hidden; }
.battery-svg { width: 100%; height: 150px; background: #1a1a25; border-radius: 8px; }
.battery-legend {
  display: flex; gap: 20px; margin-top: 8px;
  font-size: 0.85rem; color: #aaa; justify-content: flex-end;
}

/* Export */
.export-buttons { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 4px; }
.btn-export {
  padding: 12px 24px; border: none; border-radius: 12px;
  font-size: 1rem; font-weight: bold; cursor: pointer;
  transition: all 0.2s; min-width: 160px;
}
.btn-export:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-json {
  background: linear-gradient(135deg, #3f51b5, #7c4dff);
  color: #fff;
  box-shadow: 0 4px 12px rgba(63, 81, 181, 0.35);
}
.btn-json:hover:not(:disabled) { background: linear-gradient(135deg, #5c6bc0, #9575cd); }
.btn-csv {
  background: linear-gradient(135deg, #4caf50, #2e7d32);
  color: #fff;
  box-shadow: 0 4px 12px rgba(76, 175, 80, 0.35);
}
.btn-csv:hover:not(:disabled) { background: linear-gradient(135deg, #66bb6a, #43a047); }

@media (max-width: 600px) {
  .bar { width: 24px; }
  .bar-label { font-size: 0.7rem; }
  .figurine-info { flex: 0 0 100px; }
  .export-buttons { flex-direction: column; }
  .btn-export { width: 100%; }
}
</style>

