<template>
  <div class="admin-offline-voice">

    <div class="header-section">
      <h2>🎙️ Voce offline (Piper)</h2>
      <p>Configura il motore TTS locale per la sintesi vocale senza connessione internet.</p>
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- Piper status card -->
    <div class="card">
      <h3>Stato Piper 🔍</h3>
      <div v-if="loadingStatus" class="loading-text">Verifica in corso... ⏳</div>
      <div v-else-if="status">
        <div class="status-grid">
          <div class="status-item">
            <span class="status-label">Piper installato</span>
            <span class="status-value" :class="status.piper_available ? 'text-green' : 'text-red'">
              {{ status.piper_available ? '✅ Sì' : '❌ Non trovato' }}
            </span>
          </div>
          <div class="status-item">
            <span class="status-label">Eseguibile</span>
            <span class="status-value mono">{{ status.piper_executable }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">Voci disponibili</span>
            <span class="status-value">{{ status.voices?.length ?? 0 }}</span>
          </div>
          <div class="status-item">
            <span class="status-label">Cache audio</span>
            <span class="status-value">{{ status.cache?.files ?? 0 }} file ({{ cacheSize }})</span>
          </div>
        </div>

        <div v-if="!status.piper_available" class="install-help">
          <h4>Come installare Piper su Raspberry Pi</h4>
          <ol>
            <li>
              Scarica il binario da
              <code>https://github.com/rhasspy/piper/releases</code>
              (RPi 4/5 a 64-bit: <code>piper_linux_aarch64.tar.gz</code>)
            </li>
            <li>Estrai e copia <code>piper</code> in <code>/usr/local/bin/</code></li>
            <li>
              Scarica un modello voce (.onnx + .onnx.json) da
              <code>https://huggingface.co/rhasspy/piper-voices</code>
            </li>
            <li>
              Copia i file nella cartella <code>data/piper_voices/</code>
              (es. <code>it_IT-paola-medium.onnx</code>)
            </li>
            <li>
              Oppure imposta <code>GUFOBOX_PIPER_BIN</code> nel file <code>.env</code>
              se il binario è in un percorso diverso.
            </li>
          </ol>
        </div>
      </div>
      <button class="btn-secondary" @click="loadStatus">🔄 Ricarica stato</button>
    </div>

    <!-- OpenAI key status -->
    <div class="card">
      <h3>🔑 Chiave API OpenAI (TTS online)</h3>
      <p>
        La chiave OpenAI si configura tramite la variabile d'ambiente <code>OPENAI_API_KEY</code>
        oppure dal pannello <strong>Gufetto AI → Impostazioni AI</strong>.
        Non viene mai salvata nel codice sorgente.
      </p>
      <div class="status-item inline-status">
        <span class="status-label">Stato chiave</span>
        <span class="status-value" :class="openaiConfigured ? 'text-green' : 'text-red'">
          {{ openaiConfigured ? '✅ Configurata' : '❌ Non configurata' }}
        </span>
      </div>
      <p v-if="!openaiConfigured" class="hint">
        Per configurarla: imposta <code>OPENAI_API_KEY=sk-...</code> nel file <code>.env</code>
        oppure vai in <strong>Gufetto AI → Impostazioni AI</strong> e inserisci la chiave lì.
      </p>
    </div>

    <!-- Settings card -->
    <div class="card">
      <h3>Impostazioni voce offline ⚙️</h3>

      <div class="form-group">
        <label class="toggle-label">
          <input type="checkbox" v-model="settings.offline_enabled" />
          <span>Abilita sintesi vocale offline</span>
        </label>
        <p class="hint">Quando attivo, Piper viene usato come fallback o provider primario.</p>
      </div>

      <div class="form-group">
        <label>Voce locale</label>
        <select v-model="settings.offline_voice" :disabled="!voiceOptions.length">
          <option value="">— Seleziona una voce —</option>
          <option v-for="v in voiceOptions" :key="v" :value="v">{{ v }}</option>
        </select>
        <p v-if="!voiceOptions.length" class="hint">
          Nessun modello trovato in <code>data/piper_voices/</code>. Segui le istruzioni di installazione.
        </p>
      </div>

      <div class="form-group">
        <label>Politica di fallback</label>
        <select v-model="settings.fallback_policy">
          <option value="prefer_online">🌐 Preferisci online (Piper solo se offline)</option>
          <option value="auto">🔄 Automatico (Piper se OpenAI non risponde)</option>
          <option value="offline_only">📴 Solo offline (usa sempre Piper)</option>
        </select>
        <p class="hint">Controlla quando il Gufetto usa la voce locale invece di OpenAI TTS.</p>
      </div>

      <div class="form-group">
        <label class="toggle-label">
          <input type="checkbox" v-model="settings.cache_enabled" />
          <span>Abilita cache audio (velocizza frasi ripetute)</span>
        </label>
      </div>

      <div class="form-actions">
        <button class="btn-save" @click="saveSettings" :disabled="saving">
          {{ saving ? 'Salvataggio...' : '💾 Salva impostazioni' }}
        </button>
      </div>
    </div>

    <!-- Test card -->
    <div class="card">
      <h3>🔊 Test voce offline</h3>
      <p class="hint">Genera un audio di prova per verificare che Piper funzioni correttamente.</p>

      <div class="form-group">
        <label>Testo da sintetizzare</label>
        <input
          type="text"
          v-model="testText"
          placeholder="Ciao! Sono il Gufetto Magico. Come stai?"
          class="text-input"
          maxlength="200"
        />
      </div>

      <div class="form-actions">
        <button
          class="btn-test"
          @click="testVoice"
          :disabled="testing || !status?.piper_available"
        >
          {{ testing ? '⏳ Generazione...' : '▶ Prova voce' }}
        </button>
      </div>

      <div v-if="testAudioUrl" class="audio-player">
        <audio controls :src="testAudioUrl" autoplay></audio>
      </div>

      <div v-if="status && !status.piper_available" class="banner banner-warning mt-small">
        ⚠️ Piper non è installato — il test non è disponibile.
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

const loadingStatus = ref(false)
const saving = ref(false)
const testing = ref(false)
const status = ref(null)
const openaiConfigured = ref(false)
const testText = ref('Ciao! Sono il Gufetto Magico. Come stai?')
const testAudioUrl = ref(null)

const settings = reactive({
  offline_enabled: false,
  offline_voice: '',
  fallback_policy: 'auto',
  cache_enabled: true,
})

const voiceOptions = computed(() => status.value?.voices ?? [])

const cacheSize = computed(() => {
  const bytes = status.value?.cache?.bytes ?? 0
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
})

async function loadStatus() {
  loadingStatus.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/tts/offline/status'))
    status.value = data
    if (data.settings) {
      Object.assign(settings, data.settings)
    }
  } catch (e) {
    console.error('Errore caricamento stato Piper:', extractApiError(e))
  } finally {
    loadingStatus.value = false
  }
}

async function loadOpenaiStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/ai/status'))
    openaiConfigured.value = data?.openai_configured ?? false
  } catch (e) {
    openaiConfigured.value = false
  }
}

async function saveSettings() {
  saving.value = true
  clearFeedback()
  try {
    const api = getApi()
    await guardedCall(() => api.post('/tts/offline/settings', { ...settings }))
    showSuccess('Impostazioni voce offline salvate.')
  } catch (e) {
    showError(extractApiError(e, 'Errore salvataggio'))
  } finally {
    saving.value = false
  }
}

async function testVoice() {
  testing.value = true
  testAudioUrl.value = null
  clearFeedback()
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/tts/offline/test', {
      text: testText.value || 'Ciao! Sono il Gufetto Magico.',
      voice: settings.offline_voice,
    }))
    testAudioUrl.value = data.audio_url
  } catch (e) {
    showError(extractApiError(e, 'Test voce fallito'))
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadStatus()
  loadOpenaiStatus()
})
</script>

<style scoped>
.admin-offline-voice {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

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
.banner-close { background: none; border: none; cursor: pointer; opacity: 0.7; color: inherit; font-size: 1rem; padding: 0 4px; }
.banner-close:hover { opacity: 1; }
.mt-small { margin-top: 10px; }

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
  margin-bottom: 15px;
}

.loading-text { color: #aaa; font-style: italic; }

.status-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 15px;
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

.inline-status {
  display: inline-flex;
  flex-direction: row;
  align-items: center;
  gap: 12px;
  margin: 10px 0;
}

.status-label { font-size: 0.8rem; color: #aaa; }
.status-value { font-weight: bold; color: #fff; font-size: 0.95rem; }
.text-green { color: #4caf50; }
.text-red { color: #ef5350; }
.mono { font-family: monospace; font-size: 0.85rem; }

.install-help {
  background: #1e1e26;
  border-radius: 8px;
  padding: 15px;
  margin: 10px 0;
  font-size: 0.9rem;
  color: #ccc;
}

.install-help h4 {
  color: #ffd27b;
  margin: 0 0 10px 0;
  font-size: 0.95rem;
}

.install-help ol {
  margin: 0;
  padding-left: 20px;
  line-height: 1.8;
}

.install-help code {
  background: #2a2a3a;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.85rem;
  color: #44ddff;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 15px;
}

.form-group label { font-size: 0.9rem; color: #ccc; }

.form-group select {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 8px;
  border-radius: 8px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 0.95rem;
  color: #ccc;
}

.hint {
  font-size: 0.82rem;
  color: #888;
  margin: 4px 0 0 0;
}

.hint code, p code {
  background: #2a2a3a;
  padding: 1px 5px;
  border-radius: 4px;
  color: #44ddff;
  font-size: 0.82rem;
}

.text-input {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 0.95rem;
  width: 100%;
  box-sizing: border-box;
}

.form-actions {
  display: flex;
  gap: 10px;
  margin-top: 5px;
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

.btn-secondary {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
  margin-top: 10px;
}

.audio-player {
  margin-top: 15px;
}

.audio-player audio {
  width: 100%;
  border-radius: 8px;
}
</style>
