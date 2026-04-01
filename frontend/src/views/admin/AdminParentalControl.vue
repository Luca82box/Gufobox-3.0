<template>
  <div class="admin-parental">
    
    <div class="header-section">
      <h2>Parental Control 🛡️</h2>
      <p>Gestisci i limiti di ascolto e gli orari consentiti per la GufoBox.</p>
    </div>

    <div v-if="loading" class="loading-state">
      Caricamento impostazioni... ⏳
    </div>

    <div v-else class="settings-card">
      
      <div class="setting-group toggle-group">
        <div class="setting-info">
          <h3>Abilita Parental Control</h3>
          <p>Se disattivato, la GufoBox funzionerà senza alcun limite di tempo.</p>
        </div>
        <label class="switch">
          <input type="checkbox" v-model="settings.enabled">
          <span class="slider round"></span>
        </label>
      </div>

      <hr class="divider" v-if="settings.enabled" />

      <div v-if="settings.enabled" class="detailed-settings">
        
        <div class="setting-group">
          <div class="setting-info">
            <h3>Tempo massimo giornaliero ⏱️</h3>
            <p>Quanti minuti al giorno può suonare la GufoBox?</p>
          </div>
          <div class="input-wrapper">
            <input 
              type="number" 
              v-model="settings.daily_limit_minutes" 
              min="0" 
              max="1440"
            />
            <span class="unit">minuti</span>
          </div>
        </div>

        <div class="setting-group">
          <div class="setting-info">
            <h3>Fascia oraria consentita 🌙</h3>
            <p>Fuori da questi orari, la GufoBox si metterà a dormire (utile per la notte).</p>
          </div>
          <div class="time-inputs">
            <div>
              <label>Dalle:</label>
              <input type="time" v-model="settings.allow_from" />
            </div>
            <div>
              <label>Alle:</label>
              <input type="time" v-model="settings.allow_to" />
            </div>
          </div>
        </div>

        <div class="setting-group">
          <div class="setting-info">
            <h3>Volume Massimo Consigliato 🔊</h3>
            <p>Impedisce che il volume venga alzato oltre questa soglia.</p>
          </div>
          <div class="volume-slider">
            <input 
              type="range" 
              min="10" max="100" 
              v-model="settings.max_volume"
            />
            <span>{{ settings.max_volume }}%</span>
          </div>
        </div>

      </div>

      <div class="actions">
        <button class="btn-save" @click="saveSettings">
          💾 Salva Impostazioni
        </button>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

const loading = ref(false)

// Stato delle impostazioni (con valori di default)
const settings = reactive({
  enabled: false,
  daily_limit_minutes: 120,
  allow_from: '08:00',
  allow_to: '20:30',
  max_volume: 80
})

// 1. Carica le impostazioni dal server
async function loadSettings() {
  loading.value = true
  try {
    const api = getApi()
    // Nota: Creeremo questo endpoint nel backend Python!
    const { data } = await guardedCall(() => api.get('/parental/settings'))
    
    if (data) {
      settings.enabled = data.enabled || false
      settings.daily_limit_minutes = data.daily_limit_minutes || 120
      settings.allow_from = data.allow_from || '08:00'
      settings.allow_to = data.allow_to || '20:30'
      settings.max_volume = data.max_volume || 80
    }
  } catch (e) {
    console.warn('Backend non ancora pronto per il Parental Control:', extractApiError(e))
  } finally {
    loading.value = false
  }
}

// 2. Salva le impostazioni
async function saveSettings() {
  try {
    const api = getApi()
    await guardedCall(() => api.post('/parental/settings', settings))
    alert('Impostazioni del Parental Control salvate con successo!')
  } catch (e) {
    alert(extractApiError(e, 'Errore salvataggio impostazioni'))
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<style scoped>
.admin-parental {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

.settings-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 25px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.setting-group {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 15px;
  margin-bottom: 25px;
}

.setting-info h3 {
  margin: 0 0 5px 0;
  color: #ffd27b;
  font-size: 1.1rem;
}

.setting-info p {
  margin: 0;
  color: #aaa;
  font-size: 0.9rem;
  max-width: 400px;
}

.divider {
  border: 0;
  height: 1px;
  background: #3a3a48;
  margin: 20px 0;
}

/* Stili per Input */
.input-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
}

.input-wrapper input {
  width: 80px;
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 10px;
  border-radius: 8px;
  font-size: 1.1rem;
  text-align: center;
}

.unit { color: #ccc; }

.time-inputs {
  display: flex;
  gap: 20px;
}

.time-inputs div {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.time-inputs label {
  font-size: 0.85rem;
  color: #aaa;
}

.time-inputs input {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 10px;
  border-radius: 8px;
  font-size: 1.1rem;
}

.volume-slider {
  display: flex;
  align-items: center;
  gap: 15px;
  min-width: 200px;
}

.volume-slider input {
  flex: 1;
}

.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}

.btn-save {
  background: #4caf50;
  color: white;
  border: none;
  padding: 12px 25px;
  border-radius: 8px;
  font-size: 1.1rem;
  font-weight: bold;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-save:hover { background: #45a049; }

/* Toggle Switch (CSS puro) */
.switch {
  position: relative;
  display: inline-block;
  width: 60px;
  height: 34px;
}

.switch input { 
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0; left: 0; right: 0; bottom: 0;
  background-color: #1e1e26;
  border: 1px solid #3a3a48;
  transition: .4s;
}

.slider:before {
  position: absolute;
  content: "";
  height: 26px;
  width: 26px;
  left: 3px;
  bottom: 3px;
  background-color: #aaa;
  transition: .4s;
}

input:checked + .slider {
  background-color: #3f51b5;
  border-color: #3f51b5;
}

input:checked + .slider:before {
  transform: translateX(26px);
  background-color: white;
}

.slider.round {
  border-radius: 34px;
}

.slider.round:before {
  border-radius: 50%;
}
</style>

