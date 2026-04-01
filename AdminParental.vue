<template>
  <div class="admin-parental">
    <div class="header-section">
      <h2>Parental Control 🛡️</h2>
      <p>Imposta i limiti di utilizzo per proteggere il sonno e l'udito del tuo bambino.</p>
    </div>

    <div v-if="loading" class="loading-state">Caricamento impostazioni... ⏳</div>

    <div v-else class="settings-card">
      <div class="status-header">
        <h3>Stato Parental Control</h3>
        <label class="switch">
          <input type="checkbox" v-model="settings.enabled">
          <span class="slider round"></span>
        </label>
      </div>

      <div :class="['controls-wrapper', { 'is-disabled': !settings.enabled }]">
        
        <div class="control-group">
          <label>Volume Massimo Consentito: {{ settings.max_volume }}%</label>
          <p class="help-text">Blocca il volume per evitare che venga alzato troppo dai pulsanti fisici.</p>
          <input 
            type="range" 
            v-model="settings.max_volume" 
            min="10" max="100" step="5"
            :disabled="!settings.enabled"
          />
        </div>

        <hr class="divider" />

        <div class="control-group">
          <label>Fascia Oraria Consentita</label>
          <p class="help-text">Al di fuori di questi orari, la GufoBox dirà che sta dormendo.</p>
          <div class="time-inputs">
            <div class="time-box">
              <span>Dalle:</span>
              <input type="time" v-model="settings.allow_from" :disabled="!settings.enabled" />
            </div>
            <div class="time-box">
              <span>Alle:</span>
              <input type="time" v-model="settings.allow_to" :disabled="!settings.enabled" />
            </div>
          </div>
        </div>

        <hr class="divider" />

        <div class="control-group">
          <label>Limite di Ascolto Giornaliero (Minuti)</label>
          <p class="help-text">Tempo massimo di riproduzione al giorno (es. 120 = 2 ore).</p>
          <input 
            type="number" 
            v-model="settings.daily_limit_minutes" 
            min="0" max="720"
            :disabled="!settings.enabled"
          />
        </div>

      </div>

      <div class="actions">
        <button class="btn-save" @click="saveSettings" :disabled="isSaving">
          {{ isSaving ? 'Salvataggio...' : '💾 Salva Restrizioni' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

const loading = ref(true)
const isSaving = ref(false)
const settings = ref({
  enabled: false,
  daily_limit_minutes: 120,
  allow_from: '08:00',
  allow_to: '20:30',
  max_volume: 80
})

async function loadSettings() {
  loading.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/parental/settings'))
    settings.value = data
  } catch (e) {
    console.error('Errore caricamento parental control:', e)
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  isSaving.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/parental/settings', settings.value))
    alert('Impostazioni Parental Control salvate con successo!')
  } catch (e) {
    alert(extractApiError(e, 'Errore durante il salvataggio'))
  } finally {
    isSaving.value = false
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<style scoped>
.admin-parental { display: flex; flex-direction: column; gap: 20px; }
.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

.settings-card {
  background: #2a2a35; border-radius: 12px; padding: 25px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.status-header {
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid #3a3a48; padding-bottom: 15px; margin-bottom: 20px;
}
.status-header h3 { margin: 0; color: #ffd27b; }

.controls-wrapper.is-disabled { opacity: 0.5; pointer-events: none; }

.control-group { display: flex; flex-direction: column; gap: 10px; margin-bottom: 15px; }
.control-group label { color: #fff; font-weight: bold; font-size: 1.1rem; }
.help-text { margin: 0; font-size: 0.85rem; color: #888; }

input[type="range"] { width: 100%; accent-color: #3f51b5; }
input[type="number"], input[type="time"] {
  background: #1e1e26; border: 1px solid #3a3a48; color: white;
  padding: 10px; border-radius: 8px; font-size: 1.1rem; width: 100%; max-width: 200px;
}

.time-inputs { display: flex; gap: 20px; flex-wrap: wrap; }
.time-box { display: flex; align-items: center; gap: 10px; }
.time-box span { color: #ccc; font-weight: bold; }

.divider { border: 0; height: 1px; background: #3a3a48; margin: 25px 0; }

.actions { display: flex; justify-content: flex-end; margin-top: 20px; }
.btn-save { background: #4caf50; color: white; border: none; padding: 12px 25px; border-radius: 8px; font-size: 1.1rem; font-weight: bold; cursor: pointer; }

/* Toggle Switch */
.switch { position: relative; display: inline-block; width: 60px; height: 34px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #1e1e26; border: 1px solid #3a3a48; transition: .4s; }
.slider:before { position: absolute; content: ""; height: 26px; width: 26px; left: 3px; bottom: 3px; background-color: #aaa; transition: .4s; }
input:checked + .slider { background-color: #3f51b5; border-color: #3f51b5; }
input:checked + .slider:before { transform: translateX(26px); background-color: white; }
.slider.round { border-radius: 34px; }
.slider.round:before { border-radius: 50%; }
</style>

