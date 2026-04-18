<template>
  <div class="admin-parental">
    <div class="header-section">
      <h2>Parental Control 🛡️</h2>
      <p>Imposta i limiti di utilizzo e il profilo età per adattare il Gufetto al tuo bambino.</p>
    </div>

    <div v-if="loading" class="loading-state">Caricamento impostazioni... ⏳</div>

    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <div v-else-if="!loading" class="settings-card">
      <div class="status-header">
        <h3>Stato Parental Control</h3>
        <label class="switch">
          <input type="checkbox" v-model="settings.enabled">
          <span class="slider round"></span>
        </label>
      </div>

      <div :class="['controls-wrapper', { 'is-disabled': !settings.enabled }]">

        <!-- Age profile selector -->
        <div class="control-group">
          <label>Fascia d'Età del Bambino</label>
          <p class="help-text">Il Gufetto adatterà il linguaggio, i contenuti e la complessità all'età selezionata.</p>
          <div class="age-grid">
            <button
              v-for="profile in AGE_PROFILES"
              :key="profile.value"
              class="age-btn"
              :class="{ selected: settings.age_profile === profile.value }"
              :disabled="!settings.enabled"
              @click="settings.age_profile = profile.value"
            >
              <span class="age-icon">{{ profile.icon }}</span>
              <span class="age-label">{{ profile.label }}</span>
              <span class="age-sublabel">{{ profile.sub }}</span>
            </button>
          </div>
          <p v-if="settings.age_profile === '14+'" class="age-note">
            ℹ️ Con profilo 14+ il Gufetto usa un tono più maturo. I controlli di accesso rimangono comunque attivi.
          </p>
        </div>

        <hr class="divider" />

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
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

const AGE_PROFILES = [
  { value: '3-5',  icon: '👶', label: '3–5 anni',  sub: 'Bambini piccoli' },
  { value: '6-8',  icon: '🧒', label: '6–8 anni',  sub: 'Bambini medi' },
  { value: '9-12', icon: '👦', label: '9–12 anni', sub: 'Ragazzi' },
  { value: '14+',  icon: '🧑', label: '14+ anni',  sub: 'Teenagers' },
]

const loading = ref(true)
const isSaving = ref(false)
const settings = ref({
  enabled: false,
  age_profile: '6-8',
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
    settings.value = { ...settings.value, ...data }
  } catch (e) {
    console.error('Errore caricamento parental control:', e)
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  isSaving.value = true
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/parental/settings', settings.value))
    showSuccess('Impostazioni Parental Control salvate.')
  } catch (e) {
    showError(extractApiError(e, 'Errore durante il salvataggio'))
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

/* Age profile grid */
.age-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 10px;
  margin-top: 5px;
}
.age-btn {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  background: #1e1e26; border: 2px solid #3a3a48;
  border-radius: 10px; padding: 12px 8px;
  cursor: pointer; transition: border-color .2s, background .2s;
}
.age-btn:hover:not(:disabled) { border-color: #7e57c2; background: #27243a; }
.age-btn.selected { border-color: #7e57c2; background: #2d2044; }
.age-btn:disabled { cursor: not-allowed; }
.age-icon { font-size: 1.8rem; }
.age-label { font-size: .95rem; font-weight: bold; color: #fff; }
.age-sublabel { font-size: .78rem; color: #aaa; }
.age-note { font-size: .85rem; color: #90caf9; margin: 6px 0 0; font-style: italic; }

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

.loading-state { text-align: center; padding: 30px; color: #aaa; }
</style>

