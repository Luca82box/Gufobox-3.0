<template>
  <div class="admin-led">

    <div class="header-section">
      <h2>LED Master 💡</h2>
      <p>Configura l'effetto LED globale e gestisci il catalogo effetti.</p>
    </div>

    <!-- Master LED config -->
    <div class="card">
      <div class="card-header">
        <h3>Configurazione Master</h3>
        <div class="led-preview" :style="previewStyle"></div>
      </div>

      <div v-if="loadingMaster" class="loading-text">Caricamento... ⏳</div>
      <div v-else class="master-grid">
        <div class="form-group">
          <label>Effetto</label>
          <select v-model="master.effect_id">
            <option v-for="eff in effects" :key="eff.id" :value="eff.id">{{ eff.name }}</option>
          </select>
        </div>
        <div class="form-group">
          <label>Colore</label>
          <input type="color" v-model="master.color" />
        </div>
        <div class="form-group">
          <label>Luminosità {{ master.brightness }}%</label>
          <input type="range" min="0" max="100" v-model.number="master.brightness" />
        </div>
        <div class="form-group">
          <label>Velocità {{ master.speed }}%</label>
          <input type="range" min="0" max="100" v-model.number="master.speed" />
        </div>
      </div>

      <div class="override-row">
        <label class="override-label">
          <input type="checkbox" v-model="master.override" />
          Override globale (prevale sugli effetti statuine)
        </label>
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

    <!-- LED Status -->
    <div class="card">
      <h3>Stato LED</h3>
      <div v-if="status" class="status-grid">
        <div class="status-item">
          <span class="status-label">Effetto attivo</span>
          <span class="status-value">{{ status.effective_effect }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">Override attivo</span>
          <span class="status-value" :class="{ 'text-green': status.override_active }">
            {{ status.override_active ? 'Sì' : 'No' }}
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">LED abilitati</span>
          <span class="status-value">{{ status.runtime?.master_enabled ? 'Sì' : 'No' }}</span>
        </div>
      </div>
      <button class="btn-refresh" @click="loadStatus">🔄 Aggiorna</button>
    </div>

    <!-- Catalogo Effetti Custom -->
    <div class="card">
      <div class="card-header">
        <h3>Effetti LED Custom 🎨</h3>
        <div class="upload-area">
          <label class="btn-upload" title="Carica effetto da file JSON">
            📂 Carica da file
            <input type="file" accept=".json" @change="uploadEffect" style="display:none" />
          </label>
        </div>
      </div>

      <div class="effects-grid">
        <div
          v-for="eff in effects"
          :key="eff.id"
          class="effect-chip"
          :class="{ builtin: eff.builtin, active: master.effect_id === eff.id }"
          @click="master.effect_id = eff.id"
        >
          <span class="chip-name">{{ eff.name }}</span>
          <span v-if="eff.builtin" class="chip-tag">builtin</span>
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
import { ref, reactive, computed, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

const loadingMaster = ref(false)
const saving = ref(false)
const testing = ref(false)
const effects = ref([])
const status = ref(null)

const master = reactive({
  effect_id: 'solid',
  color: '#0000ff',
  brightness: 70,
  speed: 30,
  override: false,
})

const previewStyle = computed(() => ({
  background: master.color,
  opacity: master.brightness / 100,
}))

async function loadMaster() {
  loadingMaster.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/led/master'))
    Object.assign(master, data)
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
  try {
    const api = getApi()
    await guardedCall(() => api.post('/led/master', { ...master }))
    if (master.override !== undefined) {
      await guardedCall(() => api.post('/led/master/override', { override: master.override }))
    }
    await loadStatus()
    alert('Configurazione LED salvata!')
  } catch (e) {
    alert(extractApiError(e, 'Errore salvataggio'))
  } finally {
    saving.value = false
  }
}

async function testEffect() {
  testing.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/led/effects/test', {
      effect_id: master.effect_id,
      color: master.color,
      brightness: master.brightness,
      speed: master.speed,
    }))
  } catch (e) {
    alert(extractApiError(e, 'Errore test effetto'))
  } finally {
    testing.value = false
  }
}

async function uploadEffect(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const formData = new FormData()
  formData.append('file', file)
  try {
    const api = getApi()
    await api.post('/led/effects/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    await loadEffects()
    alert('Effetto caricato con successo!')
  } catch (e) {
    alert(extractApiError(e, 'Errore caricamento effetto'))
  }
  event.target.value = ''
}

async function deleteEffect(effectId) {
  if (!confirm(`Eliminare l'effetto "${effectId}"?`)) return
  try {
    const api = getApi()
    await api.delete(`/led/effects/${effectId}`)
    await loadEffects()
  } catch (e) {
    alert(extractApiError(e, 'Errore eliminazione effetto'))
  }
}

onMounted(() => {
  loadMaster()
  loadEffects()
  loadStatus()
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
.status-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 15px;
  margin-bottom: 12px;
}

.status-item {
  background: #1e1e26;
  padding: 10px 15px;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.status-label { font-size: 0.8rem; color: #aaa; }
.status-value { font-weight: bold; color: #fff; }
.text-green { color: #4caf50; }

.btn-refresh {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
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

.effect-chip:hover {
  background: #2a2a35;
}

.effect-chip.active {
  border-color: #ffd27b;
  background: #2a2a35;
  color: #ffd27b;
}

.effect-chip.builtin { border-style: dashed; }

.chip-name { color: #fff; }
.chip-tag { font-size: 0.7rem; color: #888; background: #333; padding: 2px 6px; border-radius: 10px; }

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
