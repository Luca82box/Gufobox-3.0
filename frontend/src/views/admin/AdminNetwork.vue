<template>
  <div class="admin-network">
    
    <div class="header-section">
      <h2>Rete Wi-Fi 📶</h2>
      <p>Collega la GufoBox a Internet per aggiornamenti, radio e podcast.</p>
    </div>

    <div class="current-network-card">
      <div class="network-info">
        <h3>Stato Connessione</h3>
        <div v-if="loadingStatus" class="loading-text">Verifica in corso... ⏳</div>
        <div v-else-if="currentNetwork" class="connected-state">
          <div class="status-icon text-green">✔️</div>
          <div class="status-details">
            <p class="ssid">Connesso a: <strong>{{ currentNetwork.ssid }}</strong></p>
            <p class="ip">Indirizzo IP: {{ currentNetwork.ip }}</p>
            <p class="signal">Segnale: {{ currentNetwork.signal }}% 📶</p>
          </div>
        </div>
        <div v-else class="disconnected-state">
          <div class="status-icon text-red">❌</div>
          <p>Nessuna connessione attiva. Seleziona una rete qui sotto.</p>
        </div>
      </div>
    </div>

    <div class="networks-card">
      <div class="card-header">
        <h3>Reti Disponibili</h3>
        <button class="btn-scan" @click="scanNetworks" :disabled="isScanning">
          {{ isScanning ? 'Scansione... 📡' : '🔄 Cerca Reti' }}
        </button>
      </div>

      <div v-if="isScanning" class="loading-state">
        Ricerca delle reti Wi-Fi nelle vicinanze...
      </div>

      <div v-else-if="availableNetworks.length === 0" class="empty-state">
        Nessuna rete trovata. Riprova la scansione.
      </div>

      <div v-else class="networks-list">
        <div 
          v-for="net in availableNetworks" 
          :key="net.ssid" 
          class="network-item"
          @click="selectNetwork(net)"
        >
          <div class="net-left">
            <span class="net-icon">📶</span>
            <span class="net-ssid">{{ net.ssid }}</span>
          </div>
          <div class="net-right">
            <span v-if="net.secure" class="net-secure" title="Rete Protetta">🔒</span>
            <span v-else class="net-open" title="Rete Aperta">🔓</span>
            <span class="net-signal">{{ net.signal }}%</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="selectedNetwork" class="password-modal" @click.self="cancelConnect">
      <div class="modal-content">
        <h3>Connetti a "{{ selectedNetwork.ssid }}"</h3>
        
        <div v-if="selectedNetwork.secure" class="form-group">
          <label>Password Wi-Fi</label>
          <input 
            type="password" 
            v-model="wifiPassword" 
            placeholder="Inserisci la password..." 
            @keyup.enter="connectToNetwork"
          />
        </div>
        <div v-else class="open-network-warning">
          Questa è una rete aperta e non richiede password.
        </div>

        <div class="modal-actions">
          <button class="btn-cancel" @click="cancelConnect">Annulla</button>
          <button class="btn-connect" @click="connectToNetwork" :disabled="isConnecting || (selectedNetwork.secure && wifiPassword.length < 8)">
            {{ isConnecting ? 'Connessione...' : 'Connetti 🚀' }}
          </button>
        </div>
      </div>
    </div>

    <!-- HOTSPOT -->
    <div class="hotspot-card">
      <div class="card-header">
        <h3>Hotspot Wi-Fi 📡</h3>
      </div>
      <p class="hotspot-desc">
        Se non c'è una rete Wi-Fi disponibile, puoi attivare il punto di accesso GufoBox 
        per connetterti direttamente con uno smartphone o tablet.
      </p>
      <div class="hotspot-status" :class="{ active: hotspotActive }">
        <span v-if="hotspotActive">✅ Hotspot attivo — SSID: <strong>{{ hotspotSsid }}</strong></span>
        <span v-else>⭕ Hotspot non attivo</span>
      </div>
      <div class="hotspot-actions">
        <button
          class="btn-hotspot-start"
          @click="startHotspot"
          :disabled="hotspotLoading || hotspotActive"
        >
          {{ hotspotLoading ? 'Avvio...' : '▶ Attiva Hotspot' }}
        </button>
        <button
          class="btn-hotspot-stop"
          @click="stopHotspot"
          :disabled="hotspotLoading || !hotspotActive"
        >
          ⏹ Disattiva
        </button>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

// Stato Rete Attuale
const currentNetwork = ref(null)
const loadingStatus = ref(false)

// Scansione Reti
const availableNetworks = ref([])
const isScanning = ref(false)

// Connessione
const selectedNetwork = ref(null)
const wifiPassword = ref('')
const isConnecting = ref(false)

// Hotspot
const hotspotActive = ref(false)
const hotspotSsid = ref('')
const hotspotLoading = ref(false)

// 1. Carica lo stato attuale
async function loadNetworkStatus() {
  loadingStatus.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/network/status'))
    currentNetwork.value = data?.connected ? data : null
    hotspotActive.value = data?.hotspot_active || false
    hotspotSsid.value = data?.hotspot_ssid || ''
  } catch (e) {
    console.error('Errore stato rete:', extractApiError(e))
  } finally {
    loadingStatus.value = false
  }
}

// 2. Scansiona reti vicine
async function scanNetworks() {
  isScanning.value = true
  availableNetworks.value = []
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/network/scan'))
    // Il backend dovrebbe restituire un array: [{ ssid: 'Casa', secure: true, signal: 90 }, ...]
    availableNetworks.value = data?.networks || []
  } catch (e) {
    alert(extractApiError(e, 'Errore durante la scansione delle reti'))
  } finally {
    isScanning.value = false
  }
}

// 3. Modale di connessione
function selectNetwork(net) {
  selectedNetwork.value = net
  wifiPassword.value = ''
}

function cancelConnect() {
  selectedNetwork.value = null
  wifiPassword.value = ''
}

// 4. Invia comando di connessione
async function connectToNetwork() {
  if (!selectedNetwork.value) return
  isConnecting.value = true
  
  try {
    const api = getApi()
    await guardedCall(() => api.post('/network/connect', {
      ssid: selectedNetwork.value.ssid,
      password: wifiPassword.value
    }))
    
    alert('Comando inviato! La GufoBox proverà a connettersi. Potresti perdere la connessione temporaneamente.')
    cancelConnect()
    
    // Attendi un po' prima di ricaricare lo stato
    setTimeout(loadNetworkStatus, 10000)
    
  } catch (e) {
    alert(extractApiError(e, 'Errore di connessione'))
  } finally {
    isConnecting.value = false
  }
}

onMounted(() => {
  loadNetworkStatus()
  // Non scansioniamo in automatico per non bloccare il chip Wi-Fi appena si apre la pagina
})

// Hotspot
async function startHotspot() {
  hotspotLoading.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/network/hotspot/start'))
    await loadNetworkStatus()
  } catch (e) {
    alert(extractApiError(e, 'Errore avvio hotspot'))
  } finally {
    hotspotLoading.value = false
  }
}

async function stopHotspot() {
  hotspotLoading.value = true
  try {
    const api = getApi()
    await guardedCall(() => api.post('/network/hotspot/stop'))
    await loadNetworkStatus()
  } catch (e) {
    alert(extractApiError(e, 'Errore arresto hotspot'))
  } finally {
    hotspotLoading.value = false
  }
}
</script>

<style scoped>
.admin-network {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

.current-network-card, .networks-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.current-network-card h3, .card-header h3 {
  margin-top: 0;
  color: #ffd27b;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
  margin-bottom: 15px;
}

.card-header h3 { border-bottom: none; padding-bottom: 0; }

.connected-state {
  display: flex;
  align-items: center;
  gap: 15px;
  background: #1e1e26;
  padding: 15px;
  border-radius: 8px;
  border-left: 4px solid #4caf50;
}

.disconnected-state {
  display: flex;
  align-items: center;
  gap: 15px;
  background: #1e1e26;
  padding: 15px;
  border-radius: 8px;
  border-left: 4px solid #ff4d4d;
  color: #aaa;
}

.status-icon { font-size: 2rem; }
.text-green { color: #4caf50; }
.text-red { color: #ff4d4d; }

.status-details p { margin: 5px 0; }
.ssid { font-size: 1.1rem; color: #fff; }
.ip, .signal { color: #aaa; font-size: 0.9rem; }

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

.networks-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 400px;
  overflow-y: auto;
}

.network-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #1e1e26;
  padding: 12px 15px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s, transform 0.1s;
}

.network-item:hover {
  background: #3a3a48;
  transform: translateX(5px);
}

.net-left, .net-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.net-ssid { font-weight: bold; color: #fff; }
.net-signal { color: #aaa; font-size: 0.9rem; }

/* Modale Password */
.password-modal {
  position: fixed;
  top: 0; left: 0; width: 100vw; height: 100vh;
  background: rgba(0,0,0,0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: #2a2a35;
  padding: 25px;
  border-radius: 12px;
  width: 90%;
  max-width: 400px;
}

.modal-content h3 { margin-top: 0; color: #fff; }

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}

.form-group label { color: #ccc; font-size: 0.9rem; }

.form-group input {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 12px;
  border-radius: 8px;
  font-size: 1.1rem;
}

.open-network-warning {
  color: #ffd27b;
  margin-bottom: 20px;
  font-size: 0.9rem;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.btn-cancel {
  background: transparent;
  color: #ccc;
  border: 1px solid #555;
  padding: 10px 15px;
  border-radius: 8px;
  cursor: pointer;
}

.btn-connect {
  background: #4caf50;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
}

.btn-connect:disabled {
  background: #555;
  color: #888;
  cursor: not-allowed;
}

/* Hotspot */
.hotspot-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.hotspot-card .card-header h3 {
  margin-top: 0;
  color: #ffd27b;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
}

.hotspot-desc {
  color: #aaa;
  font-size: 0.9rem;
  margin: 10px 0;
}

.hotspot-status {
  background: #1e1e26;
  border-radius: 8px;
  padding: 12px 15px;
  margin: 10px 0;
  color: #aaa;
  border-left: 4px solid #555;
}

.hotspot-status.active {
  border-left-color: #4caf50;
  color: #fff;
}

.hotspot-actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}

.btn-hotspot-start {
  background: #4caf50;
  color: white;
  border: none;
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
}

.btn-hotspot-start:disabled {
  background: #555;
  color: #888;
  cursor: not-allowed;
}

.btn-hotspot-stop {
  background: #e53935;
  color: white;
  border: none;
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
}

.btn-hotspot-stop:disabled {
  background: #555;
  color: #888;
  cursor: not-allowed;
}
</style>

