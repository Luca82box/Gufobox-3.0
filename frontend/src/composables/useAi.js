import { ref, computed } from 'vue'
import { useApi } from './useApi'

// Stato condiviso
const aiSettings = ref(null)
const aiRuntime = ref(null)
const aiInputText = ref('')
const isListening = ref(false)
const speechSupported = ref(typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition))
const ttsSupported = ref(typeof window !== 'undefined' && !!window.speechSynthesis)
const aiError = ref(null)

// Istanze private per le API del browser
let recognition = null
const synth = (typeof window !== 'undefined') ? window.speechSynthesis : null

export function useAi() {
  const { apiReady, guardedCall, getApi, extractApiError } = useApi()

  // 1. Inizializzazione Riconoscimento Vocale (Browser)
  function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      speechSupported.value = false
      return
    }
    // Rileva Safari/iOS: su questi browser l'API esiste ma ha limitazioni severe
    // (non funziona in background, richiede interazione utente, instabile su iOS).
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream
    const isSafariBrowser = /^((?!chrome|android).)*safari/i.test(navigator.userAgent)
    if (isIOS || isSafariBrowser) {
      // Supporto parziale: l'API è presente ma inaffidabile. Permettiamo il tentativo
      // ma impostiamo un flag per mostrare l'avviso appropriato in toggleListening().
      speechSupported.value = true
    } else {
      speechSupported.value = true
    }
    recognition = new SpeechRecognition()
    recognition.lang = 'it-IT'
    recognition.interimResults = false
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      isListening.value = true
      aiError.value = null
      if (apiReady.value) {
        const api = getApi()
        guardedCall(() => api.post('/ai/listen/start')).catch((e) => console.error('Failed to sync listen start:', e))
      }
    }
    recognition.onend = () => {
      isListening.value = false
      if (apiReady.value) {
        const api = getApi()
        guardedCall(() => api.post('/ai/listen/stop')).catch((e) => console.error('Failed to sync listen stop:', e))
      }
    }
    recognition.onerror = (e) => {
      console.error('Errore riconoscimento vocale:', e.error)
      isListening.value = false
      if (e.error === 'not-allowed') {
        aiError.value = 'Microfono non autorizzato. Controlla i permessi del browser.'
      } else if (e.error === 'no-speech') {
        aiError.value = 'Nessun audio rilevato. Riprova.'
      } else if (e.error === 'service-not-allowed') {
        // Errore tipico di Safari iOS quando il contesto non è sicuro o l'utente non ha
        // ancora interagito con la pagina.
        aiError.value = 'Microfono non disponibile. Su Safari/iOS apri la pagina tramite HTTPS e premi prima il tasto prima di parlare.'
      } else {
        aiError.value = `Errore microfono: ${e.error}`
      }
      if (apiReady.value) {
        const api = getApi()
        guardedCall(() => api.post('/ai/listen/stop')).catch((e) => console.error('Failed to sync listen stop on error:', e))
      }
    }
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript
      if (transcript) {
        aiInputText.value = transcript
        sendAiMessage(transcript)
      }
    }
  }

  function toggleListening() {
    if (!speechSupported.value || !recognition) {
      // Messaggio differenziato per Safari/iOS dove l'API manca completamente
      const isIOS = typeof navigator !== 'undefined' &&
        /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream
      const isSafariBrowser = typeof navigator !== 'undefined' &&
        /^((?!chrome|android).)*safari/i.test(navigator.userAgent)
      if (isIOS) {
        aiError.value = 'Il riconoscimento vocale non è supportato su iOS. Usa Chrome per Android o digita il messaggio.'
      } else if (isSafariBrowser) {
        aiError.value = 'Il riconoscimento vocale non è supportato su Safari. Usa Chrome o Firefox.'
      } else {
        aiError.value = 'Il tuo browser non supporta il riconoscimento vocale.'
      }
      return
    }
    aiError.value = null
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
    aiError.value = null
    try {
      const api = getApi()
      await guardedCall(() => api.post('/ai/settings', newSettings))
      await loadAiSettings()
      return { ok: true }
    } catch (e) {
      aiError.value = extractApiError(e, 'Errore salvataggio AI')
      return { ok: false, error: aiError.value }
    }
  }

  // 3. Gestione Chat e Runtime
  function updateAiRuntime(newData) {
    aiRuntime.value = newData
  }

  async function sendAiMessage(textOverride = null) {
    const textToSend = textOverride || aiInputText.value
    if (!textToSend.trim() || !apiReady.value) return

    const backupText = aiInputText.value
    aiInputText.value = ''
    aiError.value = null

    try {
      const api = getApi()
      await guardedCall(() => api.post('/ai/chat', { text: textToSend }))
    } catch (e) {
      aiInputText.value = backupText
      aiError.value = extractApiError(e, 'Errore invio messaggio AI')
    }
  }

  async function stopAiAudio() {
    if (apiReady.value) {
      try {
        const api = getApi()
        await guardedCall(() => api.post('/ai/stop'))
      } catch (_) {}
    }
    if (synth && synth.speaking) {
      synth.cancel()
    }
  }

  async function clearAiHistory() {
    if (!apiReady.value) return { ok: false }
    aiError.value = null
    try {
      const api = getApi()
      await guardedCall(() => api.post('/ai/clear-history'))
      return { ok: true }
    } catch (e) {
      aiError.value = extractApiError(e, 'Errore pulizia chat')
      return { ok: false, error: aiError.value }
    }
  }

  async function loadAiStatus() {
    if (!apiReady.value) return null
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/ai/status'))
      return data
    } catch (_) {
      return null
    }
  }

  // 4. Utility Text-to-Speech (Browser Fallback)
  function speakBrowser(text, voiceName = null) {
    if (!synth || !text) return
    synth.cancel()
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
    ttsSupported,
    aiError,
    
    // Metodi
    initSpeechRecognition,
    toggleListening,
    loadAiSettings,
    saveAiSettings,
    updateAiRuntime,
    sendAiMessage,
    stopAiAudio,
    clearAiHistory,
    loadAiStatus,
    speakBrowser
  }
}


