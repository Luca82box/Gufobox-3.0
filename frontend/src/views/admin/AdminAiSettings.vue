<template>
  <div class="admin-ai">
    <div class="header-section">
      <h2>Gufetto Magico (AI) 🧠🦉</h2>
      <p>Configura i giochi educativi, le storie interattive e la personalità dell'assistente.</p>
    </div>

    <div class="ai-grid">
      
      <div class="settings-panel card">
        <h3>Impostazioni Personalità</h3>
        
        <div v-if="loading" class="loading">Caricamento configurazione... ⏳</div>
        
        <div v-else class="form-wrapper">
          
          <div class="input-group">
            <label>Fascia d'Età</label>
            <select v-model="settings.age_profile" @change="autoSave">
              <option value="bambino">🧒 Bambino (3-7 anni)</option>
              <option value="ragazzo">👦 Ragazzo (8-13 anni)</option>
              <option value="adulto">👨 Adulto / Genitore</option>
            </select>
          </div>

          <div class="input-group">
            <label>Modalità di Gioco / Attività</label>
            <select v-model="settings.interactive_mode" @change="autoSave">
              <option value="chat_normale">💬 Conversazione Libera</option>
              <option value="storia_interattiva">📖 Storia a Bivi (Scegli tu il finale)</option>
              <option value="quiz_animali">🦁 Gioco degli Animali (Indovina i versi)</option>
              <option value="insegnante_lingue">🌍 Insegnante di Lingue (Ripeti le parole)</option>
              <option value="indovinelli">❓ Indovinelli Magici</option>
              <option value="matematica">🧮 Sfide di Matematica</option>
            </select>
          </div>

          <div class="input-group" v-if="settings.interactive_mode === 'insegnante_lingue'">
            <label>Lingua da Insegnare</label>
            <select v-model="settings.target_lang" @change="autoSave">
              <option value="en">🇬🇧 Inglese</option>
              <option value="es">🇪🇸 Spagnolo</option>
              <option value="de">🇩🇪 Tedesco</option>
              <option value="fr">🇫🇷 Francese</option>
            </select>
          </div>
          
          <hr class="divider" />

          <button class="btn-start-game" @click="startNewGame" :disabled="isThinking">
            🔄 Avvia / Riavvia Gioco
          </button>
          
          <p class="help-text mt-3">
            Modificando queste impostazioni, il Gufetto cambierà istantaneamente il modo in cui parla ai bambini.
          </p>
        </div>
      </div>

      <div class="chat-panel card">
        <h3>Prova il Gioco! 🎮</h3>
        
        <div class="chat-history" ref="chatBox">
          <div 
            v-for="(msg, index) in chatHistory" 
            :key="index"
            :class="['chat-bubble', msg.role === 'user' ? 'user-bubble' : 'ai-bubble']"
          >
            <span class="avatar">{{ msg.role === 'user' ? '👦' : '🦉' }}</span>
            <div class="message-content">
              <p>{{ msg.text }}</p>
              
              <audio v-if="msg.audio_url" :src="msg.audio_url" controls class="mini-audio"></audio>
            </div>
          </div>
          
          <div v-if="isThinking" class="chat-bubble ai-bubble thinking">
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
            :disabled="isThinking"
          />
          <button class="btn-send" @click="sendMessage" :disabled="isThinking || !userInput.trim()">
            Invia 🚀
          </button>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall } = useApi()

const loading = ref(true)
const isThinking = ref(false)
const chatBox = ref(null)

const settings = ref({
  age_profile: 'bambino',
  interactive_mode: 'storia_interattiva',
  target_lang: 'en'
})

const chatHistory = ref([
  { role: 'ai', text: "Ciao! Sono il Gufetto Magico. Scegli un gioco a sinistra e clicca su 'Avvia Gioco' per iniziare!" }
])

const userInput = ref('')

// --- GESTIONE IMPOSTAZIONI ---
async function loadSettings() {
  loading.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/ai/settings'))
    if (data.age_profile) settings.value.age_profile = data.age_profile
    if (data.interactive_mode) settings.value.interactive_mode = data.interactive_mode
    if (data.target_lang) settings.value.target_lang = data.target_lang
  } catch (e) {
    console.error("Errore caricamento impostazioni AI", e)
  } finally {
    loading.value = false
  }
}

async function autoSave() {
  try {
    const api = getApi()
    await guardedCall(() => api.post('/ai/settings', settings.value))
  } catch (e) {
    console.error("Errore salvataggio AI", e)
  }
}

// --- GESTIONE GIOCO E CHAT ---
async function startNewGame() {
  await autoSave() // Assicura che le impostazioni siano salvate
  
  // Svuota la storia del server
  try {
    const api = getApi()
    await guardedCall(() => api.post('/ai/clear-history'))
  } catch(e) {}

  chatHistory.value = []
  
  // Invia un prompt invisibile per far cominciare l'AI
  let kickstartMessage = "Iniziamo il gioco! Fai la prima domanda o inizia la storia."
  await sendToAI(kickstartMessage, true)
}

async function sendMessage() {
  const text = userInput.value.trim()
  if (!text) return
  
  // Aggiunge visivamente il messaggio dell'utente
  chatHistory.value.push({ role: 'user', text: text })
  userInput.value = ''
  scrollToBottom()

  await sendToAI(text, false)
}

async function sendToAI(text, isHiddenPrompt = false) {
  isThinking.value = true
  scrollToBottom()

  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/ai/chat', { text }))
    
    // Aggiunge la risposta dell'AI
    chatHistory.value.push({ 
      role: 'ai', 
      text: data.reply,
      audio_url: data.audio_url // Se configurato OpenAI TTS nel backend
    })
    
    // Se è stato generato l'audio, proviamo a farlo partire in automatico
    if (data.audio_url) {
      setTimeout(() => {
        const audios = document.querySelectorAll('audio')
        if(audios.length > 0) audios[audios.length - 1].play().catch(e => console.log('Autoplay bloccato', e))
      }, 100)
    }

  } catch (e) {
    chatHistory.value.push({ role: 'ai', text: "Uhm... mi si sono arruffate le piume! C'è stato un errore di connessione. 🤕" })
  } finally {
    isThinking.value = false
    scrollToBottom()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatBox.value) {
      chatBox.value.scrollTop = chatBox.value.scrollHeight
    }
  })
}

onMounted(() => {
  loadSettings()
})
</script>

<style scoped>
.admin-ai { display: flex; flex-direction: column; gap: 20px; height: 100%; }
.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

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
.help-text { font-size: 0.85rem; color: #888; text-align: center;}

.btn-start-game { 
  background: #4caf50; color: white; border: none; padding: 15px; 
  border-radius: 8px; font-weight: bold; font-size: 1.1rem; cursor: pointer; transition: 0.2s; 
}
.btn-start-game:disabled { background: #555; cursor: not-allowed; }

/* Chat Panel Destro */
.chat-history { 
  flex: 1; overflow-y: auto; padding: 15px; 
  background: #1e1e26; border-radius: 8px; margin-bottom: 15px;
  display: flex; flex-direction: column; gap: 15px;
}

.chat-bubble { display: flex; gap: 15px; max-width: 85%; }
.chat-bubble .avatar { font-size: 1.8rem; }
.message-content { padding: 12px 18px; border-radius: 15px; font-size: 1.05rem; line-height: 1.4; }
.message-content p { margin: 0; }

.user-bubble { align-self: flex-end; flex-direction: row-reverse; }
.user-bubble .message-content { background: #3f51b5; color: white; border-top-right-radius: 0; }

.ai-bubble { align-self: flex-start; }
.ai-bubble .message-content { background: #3a3a48; color: #eee; border-top-left-radius: 0; }

.thinking .message-content { font-style: italic; color: #aaa; animation: pulse 1.5s infinite; }
@keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }

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

/* Mobile Responsive */
@media (max-width: 900px) {
  .ai-grid { grid-template-columns: 1fr; }
  .chat-history { min-height: 350px; }
}
</style>

