import { ref } from 'vue'
import axios from 'axios'
import { io } from 'socket.io-client'

const API_PORT = 5000
const ADMIN_TOKEN_KEY = 'gufobox_admin_token'

// Stato reattivo globale (condiviso tra tutti i componenti)
const apiBase = ref('')
const apiReady = ref(false)
const offline = ref(false)
const socketConnected = ref(false)
const adminToken = ref(localStorage.getItem(ADMIN_TOKEN_KEY) || '')
const batteryPercent = ref(null)  // percentuale batteria aggiornata dal socket

// Istanze private interne al modulo
let apiInstance = null
let socketInstance = null

export function useApi() {
  
  // 1. Configurazione di base di Axios con intercettore per il token
  function makeClient(baseURL) {
    const instance = axios.create({
      baseURL: `${baseURL}/api`,
      timeout: 30000,
      withCredentials: true
    })
    
    instance.interceptors.request.use((config) => {
      if (adminToken.value) {
        config.headers = config.headers || {}
        config.headers.Authorization = `Bearer ${adminToken.value}`
      }
      return config
    })
    
    return instance
  }

  // 2. Ricerca e selezione del Base URL corretto
  async function selectApiBase(lastLanIp = '') {
    const host = window.location.hostname || 'gufobox.local'
    const fixedCandidates = []
    const lastLan = localStorage.getItem('gufobox_last_lan_ip') || ''

    if (lastLanIp) fixedCandidates.push(`http://${lastLanIp}:${API_PORT}`)
    if (lastLan) fixedCandidates.push(`http://${lastLan}:${API_PORT}`)

    const candidates = [
      ...fixedCandidates,
      `http://${host}:${API_PORT}`,
      `http://gufobox.local:${API_PORT}`,
      `http://192.168.4.1:${API_PORT}`
    ]

    for (const base of [...new Set(candidates)]) {
      try {
        const client = makeClient(base)
        await client.get('/health')
        apiInstance = client
        apiBase.value = base
        apiReady.value = true
        offline.value = false
        return true
      } catch (_) {}
    }

    apiReady.value = false
    offline.value = true
    return false
  }

  // 3. Gestione e salvataggio del token di autenticazione
  function setAdminToken(token) {
    adminToken.value = token || ''
    if (adminToken.value) {
      localStorage.setItem(ADMIN_TOKEN_KEY, adminToken.value)
    } else {
      localStorage.removeItem(ADMIN_TOKEN_KEY)
    }
    if (apiBase.value) connectSocket() // Riconnette il socket col nuovo token auth
  }

  // 4. Wrapper protetto per le chiamate HTTP
  async function guardedCall(fn) {
    try {
      return await fn()
    } catch (e) {
      if (!e?.response) {
        apiReady.value = false
        offline.value = true
      }
      throw e
    }
  }

  // 5. Normalizzazione degli errori per l'interfaccia utente
  function extractApiError(e, fallback = 'Errore sconosciuto') {
    if (e?.response?.data?.error) return e.response.data.error
    if (e?.response?.status === 413) return "File troppo grande per l'upload HTTP"
    if (e?.code === 'ECONNABORTED') return 'Timeout richiesta: operazione troppo lunga o connessione instabile'
    if (!e?.response) return 'Backend non raggiungibile o connessione interrotta'
    return fallback
  }

  // 6. Configurazione e ciclo vitale del Socket.io
  function connectSocket(callbacks = {}) {
    if (!apiBase.value) return

    disconnectSocket()

    socketInstance = io(apiBase.value, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      withCredentials: true,
      auth: adminToken.value ? { token: adminToken.value } : {}
    })

    socketInstance.on('connect', () => {
      socketConnected.value = true
      offline.value = false
      apiReady.value = true
      if (callbacks.onConnect) callbacks.onConnect()
    })

    socketInstance.on('disconnect', () => {
      socketConnected.value = false
      if (callbacks.onDisconnect) callbacks.onDisconnect()
    })

    socketInstance.on('connect_error', () => {
      socketConnected.value = false
    })

    // Iniezione degli handler esterni
    if (callbacks.onPublicSnapshot) socketInstance.on('public_snapshot', callbacks.onPublicSnapshot)
    if (callbacks.onAdminSnapshot) socketInstance.on('admin_snapshot', callbacks.onAdminSnapshot)
    if (callbacks.onJobsUpdate) socketInstance.on('jobs_update', callbacks.onJobsUpdate)
    if (callbacks.onOtaUpdate) socketInstance.on('ota_update', callbacks.onOtaUpdate)
  }

  function disconnectSocket() {
    if (socketInstance) {
      try { socketInstance.disconnect() } catch (_) {}
      socketInstance = null
    }
    socketConnected.value = false
  }

  // Getters per le istanze pure
  const getApi = () => apiInstance
  const getSocket = () => socketInstance

  return {
    // Stato Reattivo
    apiBase,
    apiReady,
    offline,
    socketConnected,
    adminToken,
    batteryPercent,
    
    // Metodi
    selectApiBase,
    setAdminToken,
    guardedCall,
    extractApiError,
    connectSocket,
    disconnectSocket,
    getApi,
    getSocket
  }
}
