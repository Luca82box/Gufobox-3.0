import { ref, computed } from 'vue'
import { useApi } from './useApi'

// Stato condiviso
const adminUnlocked = ref(false)
const showAdmin = ref(false)

// Stato specifico del modale PIN
const showPinModal = ref(false)
const pinInput = ref('')
const pinBusy = ref(false)
const pinError = ref('')
const pinLockedRetry = ref(0)
let pinTimer = null

export function useAuth() {
  const { apiReady, guardedCall, getApi, setAdminToken } = useApi()

  // Sostituisce i numeri con i pallini per la privacy
  const maskedPin = computed(() => '●'.repeat(pinInput.value.length))

  // 1. Ripristino della sessione all'avvio
  async function restoreSession() {
    if (!apiReady.value) return false
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/auth/session'))
      adminUnlocked.value = !!(data?.authenticated || data?.token_authenticated)
      if (!adminUnlocked.value) showAdmin.value = false
      return adminUnlocked.value
    } catch (_) {
      adminUnlocked.value = false
      showAdmin.value = false
      return false
    }
  }

  // 2. Gestione Modale PIN
  function openPinModal() {
    pinInput.value = ''
    pinError.value = ''
    pinLockedRetry.value = 0
    showPinModal.value = true
  }

  function closePinModal() {
    showPinModal.value = false
  }

  // 3. Tastierino
  function addDigit(n) {
    if (pinInput.value.length < 8) pinInput.value += String(n)
  }

  function clearPin() {
    pinInput.value = ''
  }

  function backspaceDigit() {
    pinInput.value = pinInput.value.slice(0, -1)
  }

  function startPinCountdown() {
    if (pinTimer) clearInterval(pinTimer)
    pinTimer = setInterval(() => {
      if (pinLockedRetry.value > 0) pinLockedRetry.value--
      else clearInterval(pinTimer)
    }, 1000)
  }

  // 4. Login
  async function submitPin(onSuccessCallback) {
    if (!apiReady.value || !pinInput.value || pinBusy.value) return
    pinBusy.value = true
    pinError.value = ''
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/admin/login', { pin: pinInput.value }))
      
      if (data?.admin_token) setAdminToken(data.admin_token)
      
      await restoreSession()
      
      if (!adminUnlocked.value) throw new Error('auth_failed')
      
      showAdmin.value = true
      showPinModal.value = false
      pinInput.value = ''
      
      // Callback per caricare i dati admin (hardware, file, ecc.)
      if (onSuccessCallback) await onSuccessCallback()
      
    } catch (e) {
      const d = e?.response?.data || {}
      pinError.value = d.error || 'PIN errato'
      pinInput.value = ''
      if (e?.response?.status === 429 && Number.isFinite(d.retry_in)) {
        pinLockedRetry.value = Number(d.retry_in)
        startPinCountdown()
      }
    } finally {
      pinBusy.value = false
    }
  }

  // 5. Navigazione
  function goAdmin(offlineState) {
    if (offlineState) return
    if (showAdmin.value) {
      showAdmin.value = false
      return
    }
    if (adminUnlocked.value) {
      showAdmin.value = true
      return
    }
    openPinModal()
  }

  // 6. Logout
  async function logoutAdmin() {
    try {
      const api = getApi()
      await guardedCall(() => api.post('/auth/logout'))
    } catch (_) {}
    
    setAdminToken('')
    adminUnlocked.value = false
    showAdmin.value = false
  }

  // Pulizia timer se il componente viene distrutto
  function clearAuthTimers() {
    if (pinTimer) clearInterval(pinTimer)
  }

  return {
    adminUnlocked,
    showAdmin,
    showPinModal,
    pinInput,
    pinBusy,
    pinError,
    pinLockedRetry,
    maskedPin,
    restoreSession,
    openPinModal,
    closePinModal,
    addDigit,
    clearPin,
    backspaceDigit,
    submitPin,
    goAdmin,
    logoutAdmin,
    clearAuthTimers
  }
}

