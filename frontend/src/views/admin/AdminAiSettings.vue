<template>
  <div class="admin-ai">
    <div class="header-section">
      <h2>Gufetto Magico (AI) 🧠🦉</h2>
      <p>Configura i giochi educativi, le storie interattive e la personalità dell'assistente.</p>
    </div>

    <!-- AI Status Bar -->
    <div class="ai-status-bar">
      <div class="status-indicator" :class="statusClass">
        <span class="status-dot"></span>
        <span class="status-label">{{ statusLabel }}</span>
      </div>
      <div class="status-actions">
        <button
          class="btn-stop"
          @click="handleStop"
          :disabled="currentStatus === 'idle'"
          title="Ferma attività AI"
        >⏹ Stop</button>
        <button
          class="btn-reset"
          @click="handleResetChat"
          :disabled="isResetting"
          title="Cancella storico chat"
        >🧹 Reset Chat</button>
      </div>
    </div>

    <!-- Error / Warning Banner -->
    <div v-if="errorMsg" class="banner banner-error">
      <span>⚠️ {{ errorMsg }}</span>
      <button class="banner-close" @click="errorMsg = null">✕</button>
    </div>
    <div v-if="successMsg" class="banner banner-success">
      <span>✅ {{ successMsg }}</span>
      <button class="banner-close" @click="successMsg = null">✕</button>
    </div>
    <div v-if="!speechSupported" class="banner banner-warning">
      🎤 Il riconoscimento vocale non è supportato da questo browser. Usa l'input testuale.
    </div>
    <div v-if="!openaiConfigured" class="banner banner-warning">
      🔑 OpenAI non configurato: le risposte AI non saranno disponibili. Aggiungi la API Key in Impostazioni AI.
    </div>

    <div class="ai-grid">
      
      <div class="settings-panel card">
        <h3>Impostazioni Educative 🎓</h3>
        
        <div v-if="loading" class="loading">Caricamento configurazione... ⏳</div>
        
        <div v-else class="form-wrapper">
          
          <div class="input-group">
            <label>Fascia d'Età</label>
            <select v-model="settings.age_group" @change="autoSave">
              <option value="bambino">🧒 Bambino (3-7 anni)</option>
              <option value="ragazzo">👦 Ragazzo (8-13 anni)</option>
              <option value="adulto">👨 Adulto / Genitore</option>
            </select>
          </div>

          <div class="input-group">
            <label>Modalità Attività</label>
            <select v-model="settings.activity_mode" @change="autoSave">
              <option value="free_conversation">💬 Conversazione Libera</option>
              <option value="teaching_general">📚 Insegnamento Generale</option>
              <option value="interactive_story">📖 Storia Interattiva</option>
              <option value="animal_sounds_games">🦁 Animali e Versi</option>
              <option value="quiz">❓ Quiz</option>
              <option value="math">🧮 Matematica</option>
              <option value="foreign_languages">🌍 Lingue Straniere</option>
              <option value="school_conversation">🏫 Conversazione Scolastica</option>
            </select>
          </div>

          <!-- Mode description -->
          <div class="mode-description" v-if="activeModeDescription">
            <span class="mode-desc-icon">ℹ️</span>
            <span>{{ activeModeDescription }}</span>
          </div>

          <div class="input-group" v-if="settings.activity_mode === 'foreign_languages'">
            <label>Lingua da Imparare</label>
            <select v-model="settings.language_target" @change="autoSave">
              <option value="english">🇬🇧 Inglese</option>
              <option value="spanish">🇪🇸 Spagnolo</option>
              <option value="german">🇩🇪 Tedesco</option>
              <option value="french">🇫🇷 Francese</option>
              <option value="japanese">🇯🇵 Giapponese</option>
              <option value="chinese">🇨🇳 Cinese</option>
            </select>
          </div>

          <div class="input-group" v-if="settings.activity_mode === 'foreign_languages'">
            <label>Step di Apprendimento (1–10)</label>
            <div class="step-row">
              <input
                type="range"
                v-model.number="settings.learning_step"
                min="1" max="10" step="1"
                @change="autoSave"
                class="step-range"
              />
              <span class="step-badge">{{ settings.learning_step }}</span>
            </div>
            <span class="help-text-inline">{{ learningStepDescription }}</span>
          </div>
          
          <hr class="divider" />

          <button
            class="btn-start-game"
            @click="startNewGame"
            :disabled="currentStatus === 'thinking' || isResetting"
          >
            🔄 Avvia / Riavvia Attività
          </button>
          
          <p class="help-text mt-3">
            Modificando queste impostazioni, il Gufetto adatterà il suo comportamento alla fascia d'età e alla modalità selezionata.
          </p>
        </div>
      </div>

      <div class="chat-panel card">
        <h3>Prova il Gioco! 🎮</h3>
        
        <div class="chat-history" ref="chatBox">
          <!-- Empty state -->
          <div v-if="chatHistory.length === 0" class="chat-empty">
            <span>🦉</span>
            <p>Nessun messaggio. Clicca su <strong>Avvia Gioco</strong> per iniziare!</p>
          </div>

          <div 
            v-for="(msg, index) in chatHistory" 
            :key="index"
            :class="['chat-bubble', msg.role === 'user' ? 'user-bubble' : (msg.role === 'error' ? 'error-bubble' : 'ai-bubble')]"
          >
            <span class="avatar">{{ msg.role === 'user' ? '👦' : (msg.role === 'error' ? '⚠️' : '🦉') }}</span>
            <div class="message-content">
              <p>{{ msg.text }}</p>
              <span v-if="msg.ts" class="msg-timestamp">{{ formatTs(msg.ts) }}</span>
              <audio v-if="msg.audio_url" :src="msg.audio_url" controls class="mini-audio"></audio>
            </div>
          </div>
          
          <div v-if="currentStatus === 'thinking'" class="chat-bubble ai-bubble thinking">
            <span class="avatar">🦉</span>
            <div class="message-content"><p>Uhm... fammi pensare... 🤔</p></div>
          </div>
        </div>

        <div class="chat-input-area">
          <input 
            type="text" 
            v-model="userInput" 
            placeholder="Scrivi la tua risposta qui..." 
            @keyup.enter="sendMessage"
            :disabled="currentStatus === 'thinking'"
          />
          <button
            v-if="speechSupported"
            class="btn-mic"
            :class="{ listening: isListeningLocal }"
            @click="toggleMic"
            :title="isListeningLocal ? 'Ferma microfono' : 'Parla'"
            :disabled="currentStatus === 'thinking'"
          >{{ isListeningLocal ? '🔴' : '🎤' }}</button>
          <button
            class="btn-send"
            @click="sendMessage"
            :disabled="currentStatus === 'thinking' || !userInput.trim()"
          >
            Invia 🚀
          </button>
        </div>
      </div>

    </div>
  </div>

  <!-- Wizard Categories Section -->
  <div class="wizard-categories-section card" style="margin-top:1.5rem;">
    <h3>🧙 Categorie Wizard (Statuine School &amp; Entertainment)</h3>
    <p class="help-text">Configura le attività disponibili per le statuine <strong>Scuola</strong> e <strong>Intrattenimento</strong>.</p>

    <div v-if="wizardCatLoading" class="loading">Caricamento... ⏳</div>
    <div v-else class="wizard-cat-grid">
      <div v-for="(cat, catId) in wizardCategories" :key="catId" class="wizard-cat-card">
        <h4>{{ catId === 'school' ? '🏫' : '🎮' }} {{ cat.label }}</h4>
        <ul class="activity-list">
          <li v-for="act in cat.activities" :key="act.id" class="activity-item">
            <label class="activity-toggle">
              <input type="checkbox" v-model="act.enabled" @change="saveWizardCategories" />
              <span>{{ act.label }}</span>
              <code class="act-id">{{ act.id }}</code>
            </label>
          </li>
        </ul>
      </div>
    </div>
    <p v-if="wizardCatError" class="banner banner-error" style="margin-top:.5rem;">⚠️ {{ wizardCatError }}</p>
    <p v-if="wizardCatSuccess" class="banner banner-success" style="margin-top:.5rem;">✅ {{ wizardCatSuccess }}</p>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall } = useApi()

const loading = ref(true)
const isResetting = ref(false)
const chatBox = ref(null)

// Wizard categories state
const wizardCategories = ref({})
const wizardCatLoading = ref(true)
const wizardCatError = ref(null)
const wizardCatSuccess = ref(null)

const currentStatus = ref('idle')
const lastError = ref(null)
const openaiConfigured = ref(false)
const speechSupported = ref(
  typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition)
)
const isListeningLocal = ref(false)
let recognition = null

const errorMsg = ref(null)
const successMsg = ref(null)

const settings = ref({
  age_group: 'bambino',
  activity_mode: 'free_conversation',
  language_target: 'english',
  learning_step: 1,
})

const chatHistory = ref([])
const userInput = ref('')

// ── Status helpers ──────────────────────────────────────────
const STATUS_LABELS = {
  idle: '⚪ In attesa',
  listening: '🎤 In ascolto',
  thinking: '💭 Elaborazione...',
  speaking: '🔊 Risposta in riproduzione',
  error: '🔴 Errore',
}
const statusLabel = computed(() => STATUS_LABELS[currentStatus.value] || currentStatus.value)
const statusClass = computed(() => `status-${currentStatus.value}`)

// Mode descriptions (Italian)
const MODE_DESCRIPTIONS = {
  free_conversation:   'Chat libera — il Gufetto risponde adattando il tono all\'età.',
  teaching_general:    'Spiegazioni guidate, semplici o mature in base all\'età.',
  interactive_story:   'Storia interattiva — il Gufetto racconta e chiede come proseguire.',
  animal_sounds_games: 'Giochi sugli animali, versi e curiosità della natura.',
  quiz:                'Domande e risposte guidate con tono adeguato all\'età.',
  math:                'Esercizi matematici passo-passo, difficoltà adatta all\'età.',
  foreign_languages:   'Insegnamento linguistico guidato a step: vocabolario, frasi, dialoghi.',
}
const activeModeDescription = computed(() => MODE_DESCRIPTIONS[settings.value.activity_mode] || '')

const learningStepDescription = computed(() => {
  const step = settings.value.learning_step
  if (step <= 2) return 'Step 1–2: vocabolario di base e saluti'
  if (step <= 4) return 'Step 3–4: frasi semplici e ripetizione guidata'
  if (step <= 6) return 'Step 5–6: mini dialoghi e quiz lessicali'
  if (step <= 8) return 'Step 7–8: dialoghi pratici e comprensione'
  return 'Step 9–10: conversazione avanzata e temi complessi'
})

function formatTs(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

function showSuccess(msg, durationMs = 3000) {
  successMsg.value = msg
  setTimeout(() => { successMsg.value = null }, durationMs)
}

// Legacy mode name -> canonical mapping (for backward compat with old saved settings)
const LEGACY_MODE_MAP = {
  chat_normale: 'free_conversation',
  storia_interattiva: 'interactive_story',
  quiz_animali: 'animal_sounds_games',
  insegnante_lingue: 'foreign_languages',
  indovinelli: 'quiz',
  matematica: 'math',
}
const LEGACY_LANG_MAP = { en: 'english', es: 'spanish', de: 'german', fr: 'french' }

// ── Settings ────────────────────────────────────────────────
async function loadSettings() {
  loading.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/ai/settings'))
    // New canonical fields first, fall back to legacy names
    settings.value.age_group = data.age_group || data.age_profile || 'bambino'
    const rawMode = data.activity_mode || data.interactive_mode || 'free_conversation'
    settings.value.activity_mode = LEGACY_MODE_MAP[rawMode] || rawMode
    const rawLang = data.language_target || data.target_lang || 'english'
    settings.value.language_target = LEGACY_LANG_MAP[rawLang] || rawLang
    settings.value.learning_step = Math.max(1, parseInt(data.learning_step || 1, 10))
    openaiConfigured.value = (!!(data.openai_api_key && !data.openai_api_key.includes('****')))
      || (data.openai_configured === true)
  } catch (e) {
    console.error('Errore caricamento impostazioni AI', e)
  } finally {
    loading.value = false
  }
}

async function loadStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/ai/status'))
    currentStatus.value = data.status || 'idle'
    lastError.value = data.last_error || null
    openaiConfigured.value = !!data.openai_configured
    if (currentStatus.value === 'error' && lastError.value) {
      errorMsg.value = `Errore AI: ${lastError.value}`
    }
  } catch (e) { console.error('Errore caricamento stato AI', e) }
}

async function autoSave() {
  try {
    const api = getApi()
    await guardedCall(() => api.post('/ai/settings', {
      age_group: settings.value.age_group,
      activity_mode: settings.value.activity_mode,
      language_target: settings.value.language_target,
      learning_step: settings.value.learning_step,
    }))
  } catch (e) {
    console.error('Errore salvataggio AI', e)
  }
}

// ── Game / Chat ─────────────────────────────────────────────
async function startNewGame() {
  await autoSave()
  isResetting.value = true
  errorMsg.value = null
  try {
    const api = getApi()
    await guardedCall(() => api.post('/ai/clear-history'))
    chatHistory.value = []
    currentStatus.value = 'idle'
    const kickstart = 'Iniziamo il gioco! Fai la prima domanda o inizia la storia.'
    await sendToAI(kickstart, true)
  } catch (e) {
    errorMsg.value = 'Avvio gioco fallito. Riprova.'
  } finally {
    isResetting.value = false
  }
}

async function sendMessage() {
  const text = userInput.value.trim()
  if (!text) return
  chatHistory.value.push({ role: 'user', text, ts: Math.floor(Date.now() / 1000) })
  userInput.value = ''
  scrollToBottom()
  await sendToAI(text, false)
}

async function sendToAI(text, isHiddenPrompt = false) {
  currentStatus.value = 'thinking'
  errorMsg.value = null
  scrollToBottom()
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/ai/chat', { text }))
    chatHistory.value.push({
      role: 'ai',
      text: data.reply,
      audio_url: data.audio_url,
      ts: Math.floor(Date.now() / 1000),
    })
    currentStatus.value = data.audio_url ? 'speaking' : 'idle'
    if (data.audio_url) {
      setTimeout(() => {
        const audios = document.querySelectorAll('audio')
        if (audios.length > 0) audios[audios.length - 1].play().catch(() => {})
      }, 100)
    }
  } catch (e) {
    currentStatus.value = 'error'
    const msg = e?.response?.data?.error || 'Errore di connessione al Gufetto.'
    chatHistory.value.push({
      role: 'error',
      text: msg,
      ts: Math.floor(Date.now() / 1000),
    })
    errorMsg.value = msg
  } finally {
    scrollToBottom()
  }
}

// ── Controls ────────────────────────────────────────────────
async function handleStop() {
  try {
    const api = getApi()
    await guardedCall(() => api.post('/ai/stop'))
    currentStatus.value = 'idle'
    if (typeof window !== 'undefined' && window.speechSynthesis?.speaking) {
      window.speechSynthesis.cancel()
    }
  } catch (_) {}
}

async function handleResetChat() {
  isResetting.value = true
  errorMsg.value = null
  try {
    const api = getApi()
    await guardedCall(() => api.post('/ai/clear-history'))
    chatHistory.value = []
    currentStatus.value = 'idle'
    showSuccess('Storico chat cancellato.')
  } catch (e) {
    errorMsg.value = 'Reset chat fallito. Riprova.'
  } finally {
    isResetting.value = false
  }
}

// ── Speech Recognition ───────────────────────────────────────
function initSpeech() {
  if (!speechSupported.value) return
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  recognition = new SR()
  recognition.lang = 'it-IT'
  recognition.interimResults = false
  recognition.maxAlternatives = 1
  recognition.onstart = () => { isListeningLocal.value = true }
  recognition.onend = () => { isListeningLocal.value = false }
  recognition.onerror = (e) => {
    isListeningLocal.value = false
    if (e.error === 'not-allowed') {
      errorMsg.value = 'Microfono non autorizzato. Controlla i permessi del browser.'
    } else if (e.error !== 'no-speech') {
      errorMsg.value = `Errore microfono: ${e.error}`
    }
  }
  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript
    if (transcript) {
      userInput.value = transcript
      sendMessage()
    }
  }
}

function toggleMic() {
  if (!recognition) return
  errorMsg.value = null
  if (isListeningLocal.value) {
    recognition.stop()
  } else {
    recognition.start()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
  })
}

async function loadWizardCategories() {
  wizardCatLoading.value = true
  wizardCatError.value = null
  try {
    const api = await getApi()
    const res = await api.get('/ai/wizard/categories')
    wizardCategories.value = res.data
  } catch (e) {
    wizardCatError.value = 'Errore caricamento categorie wizard'
  } finally {
    wizardCatLoading.value = false
  }
}

async function saveWizardCategories() {
  wizardCatError.value = null
  wizardCatSuccess.value = null
  try {
    const api = await getApi()
    await api.post('/ai/wizard/categories', wizardCategories.value)
    wizardCatSuccess.value = 'Categorie wizard salvate'
    setTimeout(() => { wizardCatSuccess.value = null }, 3000)
  } catch (e) {
    wizardCatError.value = 'Errore salvataggio categorie wizard'
  }
}

onMounted(() => {
  loadSettings()
  loadStatus()
  initSpeech()
  loadWizardCategories()
})
</script>

<style scoped>
.admin-ai { display: flex; flex-direction: column; gap: 16px; height: 100%; }
.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

/* Status bar */
.ai-status-bar {
  display: flex; align-items: center; justify-content: space-between;
  background: #2a2a35; border-radius: 10px; padding: 10px 16px; gap: 12px;
  flex-wrap: wrap;
}
.status-indicator { display: flex; align-items: center; gap: 8px; font-weight: bold; }
.status-dot {
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
  background: #888;
}
.status-idle .status-dot    { background: #888; }
.status-listening .status-dot { background: #42a5f5; animation: blink 1s infinite; }
.status-thinking .status-dot  { background: #ffd27b; animation: pulse 1.2s infinite; }
.status-speaking .status-dot  { background: #66bb6a; animation: pulse 1.2s infinite; }
.status-error .status-dot    { background: #ef5350; }
.status-idle .status-label    { color: #aaa; }
.status-listening .status-label { color: #42a5f5; }
.status-thinking .status-label  { color: #ffd27b; }
.status-speaking .status-label  { color: #66bb6a; }
.status-error .status-label    { color: #ef5350; }

.status-actions { display: flex; gap: 8px; }
.btn-stop, .btn-reset {
  background: #3a3a48; border: 1px solid #555; color: #ccc;
  padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
  transition: background 0.15s;
}
.btn-stop:hover:not(:disabled)  { background: #c62828; color: #fff; }
.btn-reset:hover:not(:disabled) { background: #4a4a58; }
.btn-stop:disabled, .btn-reset:disabled { opacity: 0.4; cursor: not-allowed; }

/* Banners */
.banner {
  display: flex; align-items: center; justify-content: space-between;
  border-radius: 8px; padding: 10px 14px; font-size: 0.9rem;
}
.banner-error   { background: #3b1212; color: #ef9a9a; border: 1px solid #c62828; }
.banner-success { background: #1b3a1b; color: #a5d6a7; border: 1px solid #388e3c; }
.banner-warning { background: #3b2e0a; color: #ffe082; border: 1px solid #f9a825; }
.banner-close {
  background: none; border: none; color: inherit; cursor: pointer;
  font-size: 1rem; padding: 0 4px; opacity: 0.7;
}
.banner-close:hover { opacity: 1; }

.ai-grid { 
  display: grid; 
  grid-template-columns: 350px 1fr; 
  gap: 20px; 
  flex: 1;
  min-height: 500px;
}

.card { 
  background: #2a2a35; border-radius: 12px; padding: 20px; 
  box-shadow: 0 4px 10px rgba(0,0,0,0.2); 
  display: flex; flex-direction: column;
}
.card h3 { margin-top: 0; color: #ffd27b; border-bottom: 1px solid #3a3a48; padding-bottom: 10px; }

/* Form Pannello Sinistro */
.input-group { display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px; }
.input-group label { color: #fff; font-weight: bold; font-size: 0.95rem; }
.input-group select { 
  background: #1e1e26; border: 1px solid #3a3a48; color: white; 
  padding: 12px; border-radius: 8px; font-size: 1rem; outline: none;
}

.divider { border: 0; height: 1px; background: #3a3a48; margin: 10px 0 20px 0; }
.help-text { font-size: 0.85rem; color: #888; text-align: center; }
.help-text-inline { font-size: 0.8rem; color: #888; display: block; margin-top: 4px; }

/* Mode description */
.mode-description {
  display: flex; align-items: flex-start; gap: 6px;
  background: #1e2a35; border: 1px solid #2a4060; border-radius: 6px;
  padding: 8px 12px; margin-bottom: 16px; font-size: 0.85rem; color: #9ec8e0;
}
.mode-desc-icon { flex-shrink: 0; }

/* Learning step row */
.step-row { display: flex; align-items: center; gap: 10px; }
.step-range { flex: 1; accent-color: #4caf50; }
.step-badge {
  background: #3a3a48; color: #ffd27b; font-weight: bold;
  border-radius: 6px; padding: 2px 10px; min-width: 32px; text-align: center;
  font-size: 1rem;
}

.btn-start-game { 
  background: #4caf50; color: white; border: none; padding: 15px; 
  border-radius: 8px; font-weight: bold; font-size: 1.1rem; cursor: pointer; transition: 0.2s; 
}
.btn-start-game:disabled { background: #555; cursor: not-allowed; }

/* Chat Panel */
.chat-history { 
  flex: 1; overflow-y: auto; padding: 15px; 
  background: #1e1e26; border-radius: 8px; margin-bottom: 15px;
  display: flex; flex-direction: column; gap: 15px;
}
.chat-empty {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; color: #666; gap: 8px; text-align: center;
}
.chat-empty span { font-size: 2.5rem; }
.chat-empty p { margin: 0; font-size: 0.9rem; }

.chat-bubble { display: flex; gap: 15px; max-width: 85%; }
.chat-bubble .avatar { font-size: 1.8rem; }
.message-content { padding: 12px 18px; border-radius: 15px; font-size: 1.05rem; line-height: 1.4; }
.message-content p { margin: 0 0 4px; }
.msg-timestamp { font-size: 0.72rem; color: #666; display: block; }

.user-bubble { align-self: flex-end; flex-direction: row-reverse; }
.user-bubble .message-content { background: #3f51b5; color: white; border-top-right-radius: 0; }

.ai-bubble { align-self: flex-start; }
.ai-bubble .message-content { background: #3a3a48; color: #eee; border-top-left-radius: 0; }

.error-bubble { align-self: flex-start; }
.error-bubble .message-content { background: #3b1212; color: #ef9a9a; border-top-left-radius: 0; }

.thinking .message-content { font-style: italic; color: #aaa; animation: pulse 1.5s infinite; }

.mini-audio { margin-top: 10px; height: 35px; width: 100%; border-radius: 20px; }

/* Input Chat */
.chat-input-area { display: flex; gap: 10px; }
.chat-input-area input { 
  flex: 1; background: #1e1e26; border: 1px solid #3a3a48; color: white; 
  padding: 15px; border-radius: 8px; font-size: 1rem; outline: none;
}
.btn-send { 
  background: #3f51b5; color: white; border: none; padding: 0 25px; 
  border-radius: 8px; font-weight: bold; cursor: pointer; transition: 0.2s;
}
.btn-send:disabled { background: #555; color: #888; }
.btn-mic {
  background: #3a3a48; border: 1px solid #555; color: #fff;
  padding: 0 14px; border-radius: 8px; cursor: pointer; font-size: 1.2rem;
  transition: background 0.15s;
}
.btn-mic.listening { background: #c62828; border-color: #ef5350; }
.btn-mic:disabled { opacity: 0.4; cursor: not-allowed; }

/* Animations */
@keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

/* Wizard categories */
.wizard-categories-section { background: #2a2a35; border-radius: 12px; padding: 20px; }
.wizard-categories-section h3 { margin-top: 0; color: #ffd27b; border-bottom: 1px solid #3a3a48; padding-bottom: 10px; }
.wizard-cat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-top: 12px; }
.wizard-cat-card { background: #1e1e26; border-radius: 10px; padding: 14px; border: 1px solid #3a3a48; }
.wizard-cat-card h4 { margin: 0 0 10px 0; color: #a9c4e4; font-size: 1rem; }
.activity-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.activity-item { display: flex; }
.activity-toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; color: #ccc; font-size: 0.9rem; }
.activity-toggle input[type="checkbox"] { accent-color: #4caf50; width: 16px; height: 16px; }
.act-id { font-size: 0.72rem; color: #666; background: #111; border-radius: 4px; padding: 1px 5px; }

/* Mobile */
@media (max-width: 900px) {
  .ai-grid { grid-template-columns: 1fr; }
  .chat-history { min-height: 350px; }
}
</style>


