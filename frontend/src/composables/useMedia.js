import { ref, computed } from 'vue'
import { useApi } from './useApi'

// Stato condiviso
const mediaStatus = ref(null)
const currentProfile = ref(null)
const currentVolume = ref(60)
const audioStatus = ref(null)
const rssPreview = ref(null)
let volumeDebounce = null

export function useMedia() {
  const { apiReady, guardedCall, getApi, extractApiError } = useApi()

  // 1. Caricamento stato generale del player
  async function loadMediaStatus(onAiStatusUpdate = null) {
    if (!apiReady.value) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/media/status'))
      mediaStatus.value = data?.media_runtime || null
      currentProfile.value = data?.current_profile || null
      rssPreview.value = data?.media_runtime?.rss_state || null
      
      // Il backend a volte invia lo stato AI insieme ai media,
      // passiamo i dati tramite callback se necessario
      if (data?.ai_runtime && onAiStatusUpdate) {
        onAiStatusUpdate(data.ai_runtime)
      }
    } catch (_) {}
  }

  // 2. Anteprima Feed RSS
  async function fetchRssPreview(rssUrl, rssLimit) {
    const url = rssUrl?.trim()
    if (!url) {
      alert('Inserisci un URL RSS valido')
      return
    }
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/rss/fetch', {
        rss_url: url,
        rss_limit: rssLimit || 10
      }))
      rssPreview.value = data?.rss_state || null
    } catch (e) {
      alert(extractApiError(e, 'Errore fetch RSS'))
    }
  }

  // 3. Gestione Volume
  async function loadPlayerVolume() {
    if (!apiReady.value) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/volume'))
      currentVolume.value = Number(data?.volume ?? 60)
    } catch (_) {}
  }

  async function setPlayerVolume() {
    if (!apiReady.value) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/volume', { volume: currentVolume.value }))
      currentVolume.value = Number(data?.volume ?? currentVolume.value)
    } catch (e) {
      alert(extractApiError(e, 'Errore volume'))
    }
  }

  function onVolumeInput() {
    if (volumeDebounce) clearTimeout(volumeDebounce)
    volumeDebounce = setTimeout(() => setPlayerVolume(), 120)
  }

  // 4. Controlli di Trasporto (Prev, Next, Stop)
  async function mediaPrev() {
    try {
      const api = getApi()
      await guardedCall(() => api.post('/media/prev'))
      await loadMediaStatus()
    } catch (e) {
      alert(extractApiError(e, 'Errore prev'))
    }
  }

  async function mediaNext() {
    try {
      const api = getApi()
      await guardedCall(() => api.post('/media/next'))
      await loadMediaStatus()
    } catch (e) {
      alert(extractApiError(e, 'Errore next'))
    }
  }

  async function mediaStop() {
    try {
      const api = getApi()
      await guardedCall(() => api.post('/media/stop'))
      await loadMediaStatus()
    } catch (e) {
      alert(extractApiError(e, 'Errore stop'))
    }
  }

  async function mediaTogglePause() {
    try {
      const api = getApi()
      await guardedCall(() => api.post('/media/toggle_pause'))
      await loadMediaStatus()
    } catch (e) {
      alert(extractApiError(e, 'Errore play/pausa'))
    }
  }

  // 5. Utility e Variabili Calcolate (Barra di Progresso)
  function fmtTime(sec) {
    const n = Math.max(0, Math.floor(Number(sec || 0)))
    const m = Math.floor(n / 60)
    const s = n % 60
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }

  const progressCurrent = computed(() => fmtTime(mediaStatus.value?.position_sec || 0))
  const progressTotal = computed(() => fmtTime(mediaStatus.value?.duration_sec || 0))
  
  const progressPercent = computed(() => {
    const pos = Number(mediaStatus.value?.position_sec || 0)
    const dur = Number(mediaStatus.value?.duration_sec || 0)
    if (!dur) return 0
    return Math.max(0, Math.min(100, Math.round((pos / dur) * 100)))
  })

  // Pulizia timer se il componente viene distrutto
  function clearMediaTimers() {
    if (volumeDebounce) clearTimeout(volumeDebounce)
  }

  return {
    // Stato Reattivo
    mediaStatus,
    currentProfile,
    currentVolume,
    audioStatus,
    rssPreview,
    
    // Metodi API
    loadMediaStatus,
    fetchRssPreview,
    loadPlayerVolume,
    setPlayerVolume,
    onVolumeInput,
    mediaPrev,
    mediaNext,
    mediaStop,
    mediaTogglePause,
    
    // Utility e computed
    fmtTime,
    progressCurrent,
    progressTotal,
    progressPercent,
    clearMediaTimers
  }
}

