<template>
  <div class="admin-led">

    <div class="header-section">
      <h2>LED Master 💡</h2>
      <p>Configura l'effetto LED globale e gestisci il catalogo effetti.</p>
    </div>

    <!-- LED Status -->
    <div class="card status-card">
      <h3>Stato LED in tempo reale</h3>
      <div v-if="status" class="status-grid">
        <div class="status-item">
          <span class="status-label">Sorgente attiva</span>
          <span class="status-value source-badge" :class="'source-' + status.current_source">
            {{ sourceLabel(status.current_source) }}
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">Effetto applicato</span>
          <span class="status-value">{{ status.applied?.effect_id || status.effective_effect }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">Intensità</span>
          <span class="status-value">{{ status.applied?.brightness ?? '—' }}%</span>
        </div>
        <div class="status-item">
          <span class="status-label">Velocità</span>
          <span class="status-value">{{ status.applied?.speed ?? '—' }}%</span>
        </div>
        <div class="status-item">
          <span class="status-label">Override attivo</span>
          <span class="status-value" :class="{ 'text-green': status.override_active }">
            {{ status.override_active ? 'Sì' : 'No' }}
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">RFID attivo</span>
          <span class="status-value">{{ status.current_rfid || '—' }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">Stato AI</span>
          <span class="status-value">{{ status.ai_state || '—' }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">LED abilitati</span>
          <span class="status-value">{{ status.runtime?.master_enabled !== false ? 'Sì' : 'No' }}</span>
        </div>
      </div>
      <div v-else class="loading-text">Caricamento stato... ⏳</div>
      <button class="btn-refresh" @click="loadStatus">🔄 Aggiorna</button>
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- Master LED config -->
    <div class="card">
      <div class="card-header">
        <h3>Configurazione Master</h3>
        <div class="led-preview" :style="previewStyle"></div>
      </div>

      <div v-if="loadingMaster" class="loading-text">Caricamento... ⏳</div>
      <div v-else>
        <div class="master-grid">
          <div class="form-group">
            <label>Effetto</label>
            <select v-model="masterSettings.effect_id">
              <option v-for="eff in effects" :key="eff.id" :value="eff.id">{{ eff.name }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>Colore</label>
            <div class="color-wheel-wrapper">
              <div ref="colorWheelEl"></div>
              <div class="color-hex-display">
                <span class="color-swatch" :style="{ background: masterSettings.color }"></span>
                <input
                  type="text"
                  v-model="masterSettings.color"
                  @change="onHexInputChange"
                  class="hex-input"
                  maxlength="7"
                  placeholder="#0000ff"
                />
              </div>
            </div>
          </div>
          <div class="form-group">
            <label>Intensità {{ masterSettings.brightness }}%</label>
            <input type="range" min="0" max="100" v-model.number="masterSettings.brightness" />
          </div>
          <div class="form-group">
            <label>Velocità effetto {{ masterSettings.speed }}%</label>
            <input type="range" min="0" max="100" v-model.number="masterSettings.speed" />
          </div>
        </div>

        <div class="override-row">
          <label class="override-label">
            <input type="checkbox" v-model="masterOverrideActive" />
            Override globale (prevale su RFID e default)
          </label>
        </div>
      </div>

      <div class="master-actions">
        <button class="btn-save" @click="saveMaster" :disabled="saving">
          {{ saving ? 'Salvataggio...' : '💾 Salva' }}
        </button>
        <button class="btn-test" @click="testEffect" :disabled="testing">
          {{ testing ? 'Test...' : '▶ Prova Effetto' }}
        </button>
      </div>
    </div>

    <!-- Catalogo Effetti -->
    <div class="card">
      <div class="card-header">
        <h3>Catalogo Effetti 🎨</h3>
        <div class="upload-area">
          <label class="btn-upload" title="Carica effetto da file JSON">
            📂 Carica da file
            <input type="file" accept=".json" @change="uploadEffect" style="display:none" />
          </label>
        </div>
      </div>

      <div class="effects-legend">
        <span class="chip-tag">builtin</span> = effetti predefiniti &nbsp;|&nbsp;
        <span class="chip-tag custom-tag">custom</span> = effetti personalizzati
      </div>

      <div class="effects-grid">
        <div
          v-for="eff in effects"
          :key="eff.id"
          class="effect-chip"
          :class="{ builtin: eff.builtin, active: masterSettings.effect_id === eff.id }"
          @click="masterSettings.effect_id = eff.id"
        >
          <span class="chip-name">{{ eff.name }}</span>
          <span v-if="eff.builtin" class="chip-tag">builtin</span>
          <span v-else class="chip-tag custom-tag">custom</span>
          <button
            v-if="!eff.builtin"
            class="chip-delete"
            @click.stop="deleteEffect(eff.id)"
            title="Elimina effetto"
          >✕</button>
        </div>
      </div>

      <div v-if="effects.length === 0" class="empty-state">Nessun effetto disponibile</div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

const loadingMaster = ref(false)
const saving = ref(false)
const testing = ref(false)
const effects = ref([])
const status = ref(null)
const colorWheelEl = ref(null)

// Settings sub-object (mirrors backend "settings" field)
const masterSettings = reactive({
  effect_id: 'solid',
  color: '#0000ff',
  brightness: 70,
  speed: 30,
})
// Override flag (mirrors backend "override_active" field)
const masterOverrideActive = ref(false)

// iro.js color picker instance
let iroColorPicker = null
let iroSyncInProgress = false  // guard against feedback loops between picker and v-model

// Regex for validating 6-digit hex colors
const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/

const previewStyle = computed(() => ({
  background: masterSettings.color,
  opacity: masterSettings.brightness / 100,
}))

function sourceLabel(src) {
  const map = {
    default: '🌐 Default',
    master: '👑 Master',
    rfid: '🏷️ RFID',
    ai: '🤖 AI',
    test: '🔬 Test',
  }
  return map[src] || src || '—'
}

function loadIroScript() {
  return new Promise((resolve) => {
    if (window.iro) { resolve(); return }
    const script = document.createElement('script')
    script.src = '/vendor/iro.min.js'
    script.onload = resolve
    script.onerror = () => { console.warn('iro.js not available'); resolve() }
    document.head.appendChild(script)
  })
}

function initColorWheel() {
  if (!colorWheelEl.value || !window.iro) return
  iroColorPicker = new window.iro.ColorPicker(colorWheelEl.value, {
    width: 160,
    color: masterSettings.color,
    layout: [
      { component: window.iro.ui.Wheel },
      { component: window.iro.ui.Slider, options: { sliderType: 'value' } },
    ],
  })
  iroColorPicker.on('color:change', (color) => {
    if (iroSyncInProgress) return
    masterSettings.color = color.hexString
  })
}

// Sync picker when color is changed via hex text input
function onHexInputChange() {
  const val = masterSettings.color
  if (HEX_COLOR_RE.test(val) && iroColorPicker) {
    iroSyncInProgress = true
    iroColorPicker.color.hexString = val
    iroSyncInProgress = false
  }
}

// Sync picker when master settings are loaded from backend
watch(() => masterSettings.color, (newColor) => {
  if (iroSyncInProgress || !iroColorPicker) return
  if (HEX_COLOR_RE.test(newColor)) {
    iroSyncInProgress = true
    iroColorPicker.color.hexString = newColor
    iroSyncInProgress = false
  }
})

async function loadMaster() {
  loadingMaster.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/led/master'))
    // Handle new nested format
    if (data.settings) {
      Object.assign(masterSettings, data.settings)
    } else {
      // Backward compat with old flat format
      const { effect_id, color, brightness, speed, params } = data
      Object.assign(masterSettings, { effect_id, color, brightness, speed, params })
    }
    masterOverrideActive.value = data.override_active ?? data.override ?? false
  } catch (e) {
    console.error('Errore caricamento master LED:', extractApiError(e))
  } finally {
    loadingMaster.value = false
  }
}

async function loadEffects() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/led/effects'))
    effects.value = data?.effects || []
  } catch (e) {
    console.error('Errore caricamento effetti LED:', extractApiError(e))
  }
}

async function loadStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/led/status'))
    status.value = data
  } catch (e) {
    console.error('Errore stato LED:', extractApiError(e))
  }
}

async function saveMaster() {
  saving.value = true
  clearFeedback()
  try {
    const api = getApi()
    // Post new nested format
    await guardedCall(() => api.post('/led/master', {
      override_active: masterOverrideActive.value,
      settings: { ...masterSettings },
    }))
    await loadStatus()
    showSuccess('Configurazione LED salvata.')
  } catch (e) {
    showError(extractApiError(e, 'Errore salvataggio'))
  } finally {
    saving.value = false
  }
}

async function testEffect() {
  testing.value = true
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/led/effects/test', {
      effect_id: masterSettings.effect_id,
      color: masterSettings.color,
      brightness: masterSettings.brightness,
      speed: masterSettings.speed,
    }))
  } catch (e) {
    showError(extractApiError(e, 'Errore test effetto'))
  } finally {
    testing.value = false
  }
}

async function uploadEffect(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const formData = new FormData()
  formData.append('file', file)
  clearFeedback()
  try {
    const api = getApi()
    await api.post('/led/effects/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    await loadEffects()
    showSuccess('Effetto caricato con successo.')
  } catch (e) {
    showError(extractApiError(e, 'Errore caricamento effetto'))
  }
  event.target.value = ''
}

async function deleteEffect(effectId) {
  if (!confirm(`Eliminare l'effetto "${effectId}"?`)) return
  clearFeedback()
  try {
    const api = getApi()
    await api.delete(`/led/effects/${effectId}`)
    await loadEffects()
    showSuccess(`Effetto "${effectId}" eliminato.`)
  } catch (e) {
    showError(extractApiError(e, 'Errore eliminazione effetto'))
  }
}

onMounted(async () => {
  await loadMaster()
  await loadEffects()
  await loadStatus()
  await loadIroScript()
  initColorWheel()
})

onUnmounted(() => {
  if (iroColorPicker) {
    iroColorPicker.off('color:change')
    iroColorPicker = null
  }
})
</script>

<style scoped>
.admin-led {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

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

.led-preview {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 2px solid #555;
  transition: background 0.3s, opacity 0.3s;
}

.loading-text { color: #aaa; font-style: italic; }

.master-grid {
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

.form-group select, .form-group input[type="range"] {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 8px;
  border-radius: 8px;
}

.form-group input[type="color"] {
  width: 100%;
  height: 38px;
  border-radius: 8px;
  border: 1px solid #3a3a48;
  background: #1e1e26;
  cursor: pointer;
  padding: 2px;
}

/* iro.js color wheel */
.color-wheel-wrapper {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

.color-hex-display {
  display: flex;
  align-items: center;
  gap: 8px;
}

.color-swatch {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid #555;
  display: inline-block;
  flex-shrink: 0;
}

.hex-input {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 6px 8px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 0.9rem;
  width: 90px;
}

.override-row {
  margin: 10px 0;
}

.override-label {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #ccc;
  cursor: pointer;
  font-size: 0.95rem;
}

.master-actions {
  display: flex;
  gap: 10px;
  margin-top: 15px;
  flex-wrap: wrap;
}

.btn-save {
  background: #4caf50;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
}

.btn-save:disabled { background: #555; color: #888; cursor: not-allowed; }

.btn-test {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  cursor: pointer;
}

.btn-test:disabled { background: #555; color: #888; cursor: not-allowed; }

/* Status */
.status-card .card { margin-bottom: 0; }

.status-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}

.status-item {
  background: #1e1e26;
  padding: 10px 15px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 120px;
}

.status-label { font-size: 0.8rem; color: #aaa; }
.status-value { font-weight: bold; color: #fff; font-size: 0.95rem; }
.text-green { color: #4caf50; }

.source-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 0.85rem;
}
.source-default { background: #333; color: #aaa; }
.source-master { background: #4a3000; color: #ffd27b; }
.source-rfid { background: #003040; color: #44ddff; }
.source-ai { background: #200040; color: #cc88ff; }
.source-test { background: #004020; color: #44ff88; }

.btn-refresh {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
}

/* Effects legend */
.effects-legend {
  font-size: 0.82rem;
  color: #888;
  margin: 8px 0 4px 0;
}

/* Effects grid */
.upload-area .btn-upload {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
}

.effects-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 15px;
}

.effect-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #1e1e26;
  border: 1px solid #3a3a48;
  border-radius: 20px;
  padding: 6px 14px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  font-size: 0.9rem;
}

.effect-chip:hover { background: #2a2a35; }

.effect-chip.active {
  border-color: #ffd27b;
  background: #2a2a35;
  color: #ffd27b;
}

.effect-chip.builtin { border-style: dashed; }

.chip-name { color: #fff; }
.chip-tag { font-size: 0.7rem; color: #888; background: #333; padding: 2px 6px; border-radius: 10px; }
.custom-tag { color: #44ddff; background: #002030; }

.chip-delete {
  background: transparent;
  border: none;
  color: #ff4d4d;
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0 2px;
  line-height: 1;
}

.empty-state {
  text-align: center;
  padding: 20px;
  color: #aaa;
  font-style: italic;
}
</style>
