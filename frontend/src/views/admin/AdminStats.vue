<template>
  <div class="admin-stats">
    <div class="header-section">
      <h2>Statistiche di Ascolto 📊</h2>
      <p>Scopri quanto tempo il tuo bambino passa ad ascoltare storie e musica.</p>
    </div>

    <div class="stats-card">
      <h3>Ultimi 7 Giorni</h3>
      
      <div v-if="loading" class="loading-state">Elaborazione dati... ⏳</div>
      
      <div v-else-if="stats.length === 0" class="empty-state">
        Non ci sono ancora dati sufficienti. Torna dopo aver usato la GufoBox!
      </div>

      <div v-else class="chart-container">
        <div class="bar-chart">
          <div 
            v-for="stat in stats" 
            :key="stat.date" 
            class="bar-wrapper"
          >
            <div class="bar-value">{{ stat.minutes }} min</div>
            <div class="bar" :style="{ height: getBarHeight(stat.minutes) + '%' }"></div>
            <div class="bar-label">{{ formatDate(stat.date) }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall } = useApi()

const loading = ref(true)
const stats = ref([])
const maxMinutes = ref(0)

async function loadStats() {
  loading.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/stats/daily'))
    
    // Inverte l'array per mostrare da sinistra (più vecchio) a destra (oggi)
    stats.value = (data || []).reverse()
    
    // Trova il giorno con più ascolti per calcolare l'altezza massima delle barre
    maxMinutes.value = Math.max(...stats.value.map(s => s.minutes), 60) // Base minima 60 min per non avere barre giganti con 2 minuti
  } catch (e) {
    console.error('Errore caricamento statistiche:', e)
  } finally {
    loading.value = false
  }
}

function getBarHeight(minutes) {
  if (maxMinutes.value === 0) return 0
  return (minutes / maxMinutes.value) * 100
}

function formatDate(dateStr) {
  // Converte "2026-03-31" in "31 Mar"
  const date = new Date(dateStr)
  return date.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
}

onMounted(() => {
  loadStats()
})
</script>

<style scoped>
.admin-stats { display: flex; flex-direction: column; gap: 20px; }
.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

.stats-card {
  background: #2a2a35; border-radius: 12px; padding: 25px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.stats-card h3 { margin-top: 0; color: #ffd27b; border-bottom: 1px solid #3a3a48; padding-bottom: 15px; }

.empty-state { text-align: center; color: #aaa; padding: 40px 0; font-style: italic; }

.chart-container {
  height: 300px;
  margin-top: 40px;
  padding-bottom: 20px;
}

.bar-chart {
  display: flex;
  justify-content: space-around;
  align-items: flex-end;
  height: 100%;
  border-bottom: 2px solid #3a3a48;
}

.bar-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  flex: 1;
  gap: 10px;
}

.bar {
  width: 40px;
  background: linear-gradient(180deg, #4caf50 0%, #3f51b5 100%);
  border-radius: 6px 6px 0 0;
  min-height: 5px;
  transition: height 0.5s ease-out;
}

.bar-value { color: #fff; font-size: 0.9rem; font-weight: bold; }
.bar-label { color: #aaa; font-size: 0.85rem; margin-top: 10px; }

@media (max-width: 600px) {
  .bar { width: 25px; }
  .bar-label { font-size: 0.75rem; }
}
</style>

