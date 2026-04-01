import { ref, computed } from 'vue'
import { useApi } from './useApi'

// Stato condiviso
const aiSettings = ref(null)
const aiRuntime = ref(null)
const aiInputText = ref('')
const isListening = ref(false)
const speechSupported = ref(false)

// Istanze private per le API del browser
let recognition = null
let synth = window.speechSynthesis

export function useAi() {
  const { apiReady, guardedCall, getApi, extractApiError } = useApi()

  // 1. Inizializzazione Riconoscimento Vocale (Browser)
  function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      speechSupported.value = false
      return
    }
    speechSupported.value = true
    recognition = new SpeechRecognition()
    recognition.lang = 'it-IT' // In futuro potremo cambiarla dinamicamente per i quiz di lingue (Richiesta #14)
    recognition.interimResults = false
    recognition.maxAlternatives = 1

    recognition.onstart = () => { isListening.value = true }
    recognition.onend = () => { isListening.value = false }
    recognition.onerror = (e) => {
      console.error('Errore riconoscimento vocale:', e.error)
      isListening.value = false
    }
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript
      if (transcript) {
        aiInputText.value = transcript
        sendAiMessage(transcript) // Invia automaticamente il messaggio
      }
    }
  }

  function toggleListening() {
    if (!speechSupported.value || !recognition) {
      alert('Il tuo browser non supporta il riconoscimento vocale.')
      return
    }
    if (isListening.value) {
      recognition.stop()
    } else {
      recognition.start()
    }
  }

  // 2. Lettura ed Aggiornamento Impostazioni AI
  async function loadAiSettings() {
    if (!apiReady.value) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/ai/settings'))
      aiSettings.value = data || null
    } catch (_) {}
  }

  async function saveAiSettings(newSettings) {
    if (!apiReady.value) return
    try {
      const api = getApi()
      await guardedCall(() => api.post('/ai/settings', newSettings))
      await loadAiSettings()
      alert('Impostazioni AI salvate con successo!')
    } catch (e) {
      alert(extractApiError(e, 'Errore salvataggio AI'))
    }
  }

  // 3. Gestione Chat e Runtime
  function updateAiRuntime(newData) {
    // Chiamato tipicamente dal Socket.io o dal polling per aggiornare la chat in tempo reale
    aiRuntime.value = newData
  }

  async function sendAiMessage(textOverride = null) {
    const textToSend = textOverride || aiInputText.value
    if (!textToSend.trim() || !apiReady.value) return

    const backupText = aiInputText.value
    aiInputText.value = '' // Pulisce subito l'input per reattività visiva

    try {
      const api = getApi()
      await guardedCall(() => api.post('/ai/chat', { text: textToSend }))
    } catch (e) {
      aiInputText.value = backupText // Ripristina in caso di errore
      alert(extractApiError(e, 'Errore invio messaggio AI'))
    }
  }

  async function stopAiAudio() {
    // Ferma l'audio del backend
    if (apiReady.value) {
      try {
        const api = getApi()
        await guardedCall(() => api.post('/ai/stop'))
      } catch (_) {}
    }
    // Ferma anche l'eventuale sintesi vocale del browser
    if (synth && synth.speaking) {
      synth.cancel()
    }
  }

  async function clearAiHistory() {
    if (!confirm('Vuoi davvero cancellare la cronologia della chat?')) return
    if (!apiReady.value) return
    try {
      const api = getApi()
      await guardedCall(() => api.post('/ai/clear'))
    } catch (e) {
      alert(extractApiError(e, 'Errore pulizia chat'))
    }
  }

  // 4. Utility Text-to-Speech (Browser Fallback)
  function speakBrowser(text, voiceName = null) {
    if (!synth || !text) return
    synth.cancel() // Ferma discorsi precedenti
    const utterance = new SpeechSynthesisUtterance(text)
    
    if (voiceName) {
      const voices = synth.getVoices()
      const selectedVoice = voices.find(v => v.name === voiceName)
      if (selectedVoice) utterance.voice = selectedVoice
    }
    
    synth.speak(utterance)
  }

  return {
    // Stato
    aiSettings,
    aiRuntime,
    aiInputText,
    isListening,
    speechSupported,
    
    // Metodi
    initSpeechRecognition,
    toggleListening,
    loadAiSettings,
    saveAiSettings,
    updateAiRuntime,
    sendAiMessage,
    stopAiAudio,
    clearAiHistory,
    speakBrowser
  }
}

