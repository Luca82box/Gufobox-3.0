<template>
  <div class="admin-bluetooth">
    
    <div class="header-section">
      <h2>Bluetooth 🛜</h2>
      <p>Collega cuffie wireless o altoparlanti esterni alla tua GufoBox.</p>
    </div>

    <div class="status-card">
      <div class="status-header">
        <div class="status-info">
          <h3>Stato Bluetooth</h3>
          <p v-if="loadingStatus">Lettura stato in corso... ⏳</p>
          <p v-else :class="isBluetoothEnabled ? 'text-green' : 'text-red'">
            <strong>{{ isBluetoothEnabled ? 'Attivo e pronto' : 'Disattivato' }}</strong>
            <span v-if="btMode && btMode !== 'idle'" class="bt-mode-badge">{{ btMode === 'sink' ? '🔊 Output verso cuffie/casse' : '🎙️ Modalità speaker' }}</span>
          </p>
        </div>
        
        <label class="switch">
          <input type="checkbox" v-model="isBluetoothEnabled" @change="toggleBluetooth">
          <span class="slider round"></span>
        </label>
      </div>

      <!-- Unblock button (for when BT is rfkill-blocked) -->
      <div v-if="!isBluetoothEnabled" class="unblock-section">
        <p class="unblock-hint">Se il Bluetooth non si attiva, potrebbe essere bloccato a livello software.</p>
        <button class="btn-unblock" @click="unblockBluetooth" :disabled="isBusy">
          🔓 Sblocca Bluetooth (rfkill)
        </button>
      </div>

      <div v-if="isBluetoothEnabled && connectedDevice" class="connected-device">
        <span class="device-icon">🎧</span>
        <div class="device-details">
          <p class="device-name">{{ connectedDevice.name || 'Dispositivo Sconosciuto' }}</p>
          <p class="device-mac">{{ connectedDevice.mac }}</p>
        </div>
        <button class="btn-disconnect" @click="disconnectDevice">Disconnetti</button>
      </div>
    </div>

    <div v-if="isBluetoothEnabled && pairedDevices.length > 0" class="devices-card">
      <h3>Dispositivi Ricordati</h3>
      <div class="devices-list">
        <div v-for="dev in pairedDevices" :key="dev.mac" class="device-item">
          <div class="device-info">
            <span class="device-name">{{ dev.name || dev.mac }}</span>
            <span class="device-mac">{{ dev.mac }}</span>
          </div>
          <div class="device-actions">
            <button class="btn-connect" @click="() => connectDevice(dev.mac)" :disabled="isBusy">Connetti</button>
            <button class="btn-forget" @click="() => forgetDevice(dev.mac)" :disabled="isBusy">Dimentica</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="isBluetoothEnabled" class="devices-card">
      <div class="card-header">
        <h3>Aggiungi Nuovo Dispositivo</h3>
        <button class="btn-scan" @click="scanDevices" :disabled="isScanning || isBusy">
          {{ isScanning ? 'Ricerca in corso... 📡' : '🔄 Cerca Cuffie/Casse' }}
        </button>
      </div>

      <div v-if="isScanning" class="loading-state">
        Metti le tue cuffie o la cassa in modalità "Pairing" (luce lampeggiante)...
      </div>
      
      <div v-else-if="discoveredDevices.length === 0" class="empty-state">
        Nessun nuovo dispositivo trovato nelle vicinanze.
      </div>

      <div v-else class="devices-list">
        <div v-for="dev in discoveredDevices" :key="dev.mac" class="device-item new-device">
          <div class="device-info">
            <span class="device-name">{{ dev.name || 'Dispositivo Sconosciuto' }}</span>
            <span class="device-mac">{{ dev.mac }}</span>
          </div>
          <div class="device-actions">
            <button class="btn-pair" @click="() => pairDevice(dev.mac)" :disabled="isBusy">
              🔗 Accoppia
            </button>
            <button class="btn-connect" @click="() => connectDevice(dev.mac)" :disabled="isBusy">
              Connetti
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Speaker mode (GufoBox as BT receiver / sink) -->
    <div v-if="isBluetoothEnabled" class="devices-card">
      <div class="card-header">
        <h3>Modalità Speaker 🔈</h3>
        <label class="switch">
          <input type="checkbox" v-model="sourceModeEnabled" @change="toggleSourceMode">
          <span class="slider round"></span>
        </label>
      </div>
      <p class="source-mode-desc">
        Abilita questa modalità per far apparire la GufoBox come <strong>cassa Bluetooth</strong>:
        potrai collegare il tuo telefono o tablet e riprodurre audio su GufoBox.
        <br><em>Nota: richiede BlueALSA / PipeWire configurato per l'audio A2DP.</em>
      </p>
      <div class="source-mode-status" :class="{ active: sourceModeEnabled }">
        <span v-if="sourceModeEnabled">✅ GufoBox visibile come speaker Bluetooth</span>
        <span v-else>⭕ Modalità speaker non attiva</span>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

// Stato
const loadingStatus = ref(false)
const isBluetoothEnabled = ref(false)
const connectedDevice = ref(null)
const pairedDevices = ref([])
const discoveredDevices = ref([])
const isScanning = ref(false)
const isBusy = ref(false)
const btMode = ref('idle')
const sourceModeEnabled = ref(false)

// 1. Carica stato iniziale
async function loadBluetoothStatus() {
  loadingStatus.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/bluetooth/status'))
    
    isBluetoothEnabled.value = data?.enabled || false
    connectedDevice.value = data?.connected_device || null
    pairedDevices.value = data?.paired_devices || []
    btMode.value = data?.mode || 'idle'
  } catch (e) {
    console.warn('Backend Bluetooth non ancora implementato', extractApiError(e))
  } finally {
    loadingStatus.value = false
  }
}

async function loadSourceModeStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/bluetooth/source-mode'))
    sourceModeEnabled.value = data?.enabled || false
  } catch (e) {
    // Best-effort
  }
}

// 2. Accendi / Spegni BT
async function toggleBluetooth() {
  try {
    const api = getApi()
    await guardedCall(() => api.post('/bluetooth/toggle', { enabled: isBluetoothEnabled.value }))
    if (!isBluetoothEnabled.value) {
      connectedDevice.value = null
      discoveredDevices.value = []
    }
  } catch (e) {
    alert(extractApiError(e, 'Errore accensione/spegnimento Bluetooth'))
    isBluetoothEnabled.value = !isBluetoothEnabled.value // Revert
  }
}

// 3. Sblocca rfkill
async function unblockBluetooth() {
  isBusy.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.post('/bluetooth/unblock'))
    if (data?.status === 'ok') {
      await loadBluetoothStatus()
    } else {
      alert('Sblocco parzialmente riuscito. Controlla il log per i dettagli.')
    }
  } catch (e) {
    alert(extractApiError(e, 'Errore sblocco Bluetooth'))
  } finally {
    isBusy.value = false
  }
}

// 4. Scansiona
async function scanDevices() {
  isScanning.value = true
  discoveredDevices.value = []
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/bluetooth/scan'))
    discoveredDevices.value = data?.devices || []
  } catch (e) {
    alert(extractApiError(e, 'Errore durante la scansione'))
  } finally {
    isScanning.value = false
  }
}

// 5. Accoppia (pair only)
async function pairDevice(mac) {
  isBusy.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/bluetooth/pair', { mac }))
    alert(`Dispositivo ${mac} accoppiato con successo!`)
    await loadBluetoothStatus()
  } catch (e) {
    alert(extractApiError(e, `Impossibile accoppiare ${mac}`))
  } finally {
    isBusy.value = false
  }
}

// 6. Connetti
async function connectDevice(mac) {
  isBusy.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/bluetooth/connect', { mac }))
    alert('Connessione stabilita!')
    await loadBluetoothStatus()
    discoveredDevices.value = []
  } catch (e) {
    alert(extractApiError(e, 'Impossibile connettersi. Assicurati che il dispositivo sia acceso.'))
  } finally {
    isBusy.value = false
  }
}

// 7. Disconnetti
async function disconnectDevice() {
  if (!connectedDevice.value) return
  isBusy.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/bluetooth/disconnect'))
    connectedDevice.value = null
  } catch (e) {
    alert(extractApiError(e, 'Errore disconnessione'))
  } finally {
    isBusy.value = false
  }
}

// 8. Dimentica (Unpair)
async function forgetDevice(mac) {
  if (!confirm('Vuoi davvero dimenticare questo dispositivo?')) return
  isBusy.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/bluetooth/forget', { mac }))
    await loadBluetoothStatus()
  } catch (e) {
    alert(extractApiError(e, 'Errore rimozione dispositivo'))
  } finally {
    isBusy.value = false
  }
}

// 9. Source mode (speaker)
async function toggleSourceMode() {
  try {
    const api = getApi()
    await guardedCall(() => api.post('/bluetooth/source-mode', { enabled: sourceModeEnabled.value }))
  } catch (e) {
    alert(extractApiError(e, 'Errore toggle modalità speaker'))
    sourceModeEnabled.value = !sourceModeEnabled.value // Revert
  }
}

onMounted(() => {
  loadBluetoothStatus()
  loadSourceModeStatus()
})
</script>

<style scoped>
.admin-bluetooth {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

.status-card, .devices-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.status-header, .card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 15px;
  margin-bottom: 15px;
}

.status-info h3, .devices-card h3 {
  margin: 0;
  color: #ffd27b;
}

.text-green { color: #4caf50; }
.text-red { color: #ff4d4d; }

.bt-mode-badge {
  margin-left: 10px;
  font-size: 0.8rem;
  background: #1e1e26;
  padding: 2px 8px;
  border-radius: 12px;
  color: #8ab4f8;
}

/* Unblock */
.unblock-section {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  border-radius: 8px;
  padding: 12px 15px;
  margin-top: 10px;
}

.unblock-hint {
  color: #aaa;
  font-size: 0.85rem;
  margin: 0 0 10px 0;
}

.btn-unblock {
  background: #ff9800;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
}

.connected-device {
  display: flex;
  align-items: center;
  gap: 15px;
  background: #1e1e26;
  padding: 15px;
  border-radius: 8px;
  border-left: 4px solid #3f51b5;
  margin-top: 10px;
}

.device-icon { font-size: 2rem; }
.device-details { flex: 1; }
.device-name { margin: 0; font-weight: bold; color: #fff; }
.device-mac { margin: 5px 0 0 0; font-size: 0.85rem; color: #aaa; }

.btn-disconnect {
  background: transparent;
  color: #ff4d4d;
  border: 1px solid #ff4d4d;
  padding: 8px 15px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-disconnect:hover {
  background: #ff4d4d;
  color: white;
}

.btn-scan {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: bold;
}

.btn-scan:disabled { opacity: 0.7; cursor: wait; }

.devices-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.device-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #1e1e26;
  padding: 12px 15px;
  border-radius: 8px;
  flex-wrap: wrap;
  gap: 10px;
}

.new-device {
  border: 1px dashed #4caf50;
}

.device-info { display: flex; flex-direction: column; }
.device-actions { display: flex; gap: 10px; }

.btn-pair {
  background: #7c4dff;
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
}

.btn-connect {
  background: #4caf50;
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}

.btn-forget {
  background: transparent;
  color: #aaa;
  border: 1px solid #555;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}

button:disabled { opacity: 0.5; cursor: not-allowed; }

/* Source mode */
.source-mode-desc {
  color: #aaa;
  font-size: 0.9rem;
  margin: 0 0 12px 0;
  line-height: 1.5;
}

.source-mode-status {
  background: #1e1e26;
  border-radius: 8px;
  padding: 10px 14px;
  color: #aaa;
  border-left: 4px solid #555;
}

.source-mode-status.active {
  border-left-color: #4caf50;
  color: #fff;
}

/* Toggle Switch */
.switch { position: relative; display: inline-block; width: 60px; height: 34px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #1e1e26; border: 1px solid #3a3a48; transition: .4s; }
.slider:before { position: absolute; content: ""; height: 26px; width: 26px; left: 3px; bottom: 3px; background-color: #aaa; transition: .4s; }
input:checked + .slider { background-color: #3f51b5; border-color: #3f51b5; }
input:checked + .slider:before { transform: translateX(26px); background-color: white; }
.slider.round { border-radius: 34px; }
.slider.round:before { border-radius: 50%; }
</style>

