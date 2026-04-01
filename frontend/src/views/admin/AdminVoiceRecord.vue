<template>
  <div class="admin-voice">
    <div class="header-section">
      <h2>Registratore Vocale 🎙️</h2>
      <p>Registra una storia o un messaggio per il bambino con la tua voce.</p>
    </div>

    <div class="recorder-card">
      <div class="mic-container">
        <button 
          class="btn-mic" 
          :class="{ 'is-recording': isRecording }"
          @click="toggleRecording"
        >
          <span v-if="!isRecording">🎙️ Clicca per Registrare</span>
          <span v-else>🛑 Ferma Registrazione ({{ recordingTime }}s)</span>
        </button>
      </div>

      <div v-if="audioUrl" class="preview-section">
        <h3>Anteprima:</h3>
        <audio :src="audioUrl" controls class="audio-player"></audio>
        
        <div class="save-form">
          <div class="form-group">
            <label>Nome della Storia</label>
            <input type="text" v-model="recordingName" placeholder="Es. Fiaba della buonanotte..." />
          </div>

          <div class="form-group">
            <label>Associa subito a una Statuina (Opzionale)</label>
            <input type="text" v-model="rfidUid" placeholder="Es. 04:B2:A1:C3" />
            <p class="help-text">Appoggia una statuina vuota per leggere il suo codice, oppure lascialo vuoto.</p>
          </div>

          <div class="actions">
            <button class="btn-discard" @click="discardRecording">🗑️ Riprova</button>
            <button class="btn-save" @click="uploadRecording" :disabled="isUploading">
              {{ isUploading ? 'Salvataggio...' : '💾 Salva sulla GufoBox' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi' // Usa il tuo composable API esistente

const { getApi, extractApiError } = useApi()

const isRecording = ref(false)
const recordingTime = ref(0)
const audioUrl = ref(null)
const recordingName = ref('')
const rfidUid = ref('')
const isUploading = ref(false)

let mediaRecorder = null
let audioChunks = []
let timerInterval = null

// 1. Avvia / Ferma registrazione
async function toggleRecording() {
  if (isRecording.value) {
    stopRecording()
  } else {
    await startRecording()
  }
}

async function startRecording() {
  try {
    // Richiede l'accesso al microfono
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    
    mediaRecorder = new MediaRecorder(stream)
    audioChunks = []

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) audioChunks.push(event.data)
    }

    mediaRecorder.onstop = () => {
      // Crea il file audio finale per l'anteprima
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' })
      audioUrl.value = URL.createObjectURL(audioBlob)
      
      // Ferma il microfono
      stream.getTracks().forEach(track => track.stop())
    }

    mediaRecorder.start()
    isRecording.value = true
    recordingTime.value = 0
    audioUrl.value = null
    
    // Avvia il timer a schermo
    timerInterval = setInterval(() => { recordingTime.value++ }, 1000)

  } catch (err) {
    alert('Errore: Impossibile accedere al microfono. Verifica i permessi del browser.')
    console.error(err)
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
  isRecording.value = false
  clearInterval(timerInterval)
}

function discardRecording() {
  audioUrl.value = null
  audioChunks = []
  recordingName.value = ''
}

// 2. Carica sul Raspberry
async function uploadRecording() {
  if (audioChunks.length === 0) return
  isUploading.value = true

  const audioBlob = new Blob(audioChunks, { type: 'audio/webm' })
  const formData = new FormData()
  
  formData.append('audio', audioBlob, 'registrazione.webm')
  if (recordingName.value) formData.append('name', recordingName.value)
  if (rfidUid.value) formData.append('rfid_uid', rfidUid.value)

  try {
    const api = getApi()
    // Siccome inviamo un file (FormData), Axios capisce da solo di usare multipart/form-data
    await api.post('/voice/upload', formData)
    
    alert('Registrazione salvata con successo sulla GufoBox!')
    discardRecording()
  } catch (err) {
    alert(extractApiError(err, 'Errore durante il salvataggio'))
  } finally {
    isUploading.value = false
  }
}

// Pulizia timer se si cambia pagina
onUnmounted(() => {
  clearInterval(timerInterval)
  if (isRecording.value) stopRecording()
})
</script>

<style scoped>
.admin-voice { display: flex; flex-direction: column; gap: 20px; }
.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

.recorder-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 30px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
  text-align: center;
}

.mic-container { margin: 20px 0; }

.btn-mic {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 20px 40px;
  font-size: 1.2rem;
  font-weight: bold;
  border-radius: 50px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 15px rgba(63, 81, 181, 0.4);
}

/* Animazione Pulsante quando registra */
.btn-mic.is-recording {
  background: #ff4d4d;
  animation: pulse-red 1.5s infinite;
  box-shadow: 0 0 20px rgba(255, 77, 77, 0.6);
}

@keyframes pulse-red {
  0% { transform: scale(1); }
  50% { transform: scale(1.05); }
  100% { transform: scale(1); }
}

.preview-section {
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid #3a3a48;
  text-align: left;
}

.audio-player { width: 100%; margin-bottom: 20px; outline: none; }

.form-group { margin-bottom: 15px; display: flex; flex-direction: column; gap: 8px; }
.form-group label { color: #ccc; font-weight: bold; }
.form-group input {
  background: #1e1e26; border: 1px solid #3a3a48; color: white;
  padding: 12px; border-radius: 8px; font-size: 1rem; width: 100%;
}
.help-text { margin: 0; font-size: 0.85rem; color: #888; }

.actions { display: flex; justify-content: flex-end; gap: 15px; margin-top: 20px; }
.btn-discard { background: transparent; color: #ff4d4d; border: 1px solid #ff4d4d; padding: 10px 20px; border-radius: 8px; cursor: pointer; }
.btn-save { background: #4caf50; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: bold; cursor: pointer; }
.btn-save:disabled { background: #555; cursor: not-allowed; }
</style>

