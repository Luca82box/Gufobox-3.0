<template>
  <div class="admin-rfid">
    
    <div class="rfid-header">
      <h2>Statuine Magiche (RFID) 🏷️</h2>
      <p>Associa i giocattoli fisici ai contenuti multimediali.</p>
    </div>

    <div class="rfid-form-card">
      <h3>{{ isEditing ? 'Modifica Associazione' : 'Nuova Statuina' }}</h3>
      
      <div class="form-grid">
        <div class="form-group">
          <label>ID Statuina (UID)</label>
          <div class="uid-input-group">
            <input 
              type="text" 
              v-model="form.uid" 
              placeholder="Es. 04:A1:B2:C3" 
              :disabled="isEditing"
            />
            <button 
              class="btn-scan" 
              @click="waitForScan"
              :class="{ 'scanning': isScanning }"
              title="Appoggia la statuina per leggere l'ID"
            >
              {{ isScanning ? 'In ascolto... 📡' : 'Scansiona 🔍' }}
            </button>
          </div>
        </div>

        <div class="form-group">
          <label>Cosa deve fare?</label>
          <select v-model="form.type">
            <option value="audio">🎵 Riproduci File/Cartella Audio</option>
            <option value="rss">📰 Leggi Notizie (Feed RSS)</option>
            <option value="ai">🦉 Avvia Comando Gufetto (AI)</option>
          </select>
        </div>

        <div class="form-group">
          <label>
            {{ form.type === 'audio' ? 'Percorso File/Cartella' : 
               form.type === 'rss' ? 'URL del Feed RSS' : 
               'Comando per il Gufetto' }}
          </label>
          <input 
            type="text" 
            v-model="form.target" 
            :placeholder="form.type === 'audio' ? '/home/gufobox/media/storia.mp3' : 'Inserisci qui...'" 
          />
        </div>
      </div>

      <!-- Blocco LED opzionale -->
      <div class="led-section">
        <div class="led-toggle" @click="form.led.enabled = !form.led.enabled">
          <span>💡 Effetto LED per questa statuina</span>
          <span class="toggle-indicator" :class="{ on: form.led.enabled }">
            {{ form.led.enabled ? 'ON' : 'OFF' }}
          </span>
        </div>
        <div v-if="form.led.enabled" class="led-config">
          <div class="led-row">
            <div class="form-group">
              <label>Effetto</label>
              <select v-model="form.led.effect_id">
                <option v-for="eff in ledEffects" :key="eff.id" :value="eff.id">{{ eff.name }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>Colore</label>
              <input type="color" v-model="form.led.color" />
            </div>
            <div class="form-group">
              <label>Luminosità {{ form.led.brightness }}%</label>
              <input type="range" min="0" max="100" v-model.number="form.led.brightness" />
            </div>
            <div class="form-group">
              <label>Velocità {{ form.led.speed }}%</label>
              <input type="range" min="0" max="100" v-model.number="form.led.speed" />
            </div>
          </div>
        </div>
      </div>

      <div class="form-actions">
        <button v-if="isEditing" class="btn-cancel" @click="resetForm">Annulla</button>
        <button class="btn-save" @click="saveMapping" :disabled="!form.uid || !form.target">
          💾 Salva Associazione
        </button>
      </div>
    </div>

    <div class="rfid-list-card">
      <h3>Statuine Configurate</h3>
      
      <div v-if="loading" class="loading-state">Caricamento in corso... ⏳</div>
      
      <div v-else-if="Object.keys(rfidMap).length === 0" class="empty-state">
        Nessuna statuina configurata. Appoggiane una per iniziare!
      </div>

      <div v-else class="rfid-grid">
        <div v-for="(data, uid) in rfidMap" :key="uid" class="rfid-item">
          
          <div class="rfid-icon">
            {{ data.type === 'audio' ? '🎵' : data.type === 'rss' ? '📰' : '🦉' }}
          </div>
          
          <div class="rfid-info">
            <h4>{{ uid }}</h4>
            <p class="target-path">{{ data.target }}</p>
            <p v-if="data.led && data.led.enabled" class="led-badge">
              💡 {{ data.led.effect_id }}
              <span class="color-dot" :style="{ background: data.led.color }"></span>
            </p>
          </div>

          <div class="rfid-actions">
            <button class="btn-icon" @click="editMapping(uid, data)" title="Modifica">✏️</button>
            <button class="btn-icon text-red" @click="deleteMapping(uid)" title="Elimina">🗑️</button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, reactive } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, getSocket, guardedCall, extractApiError } = useApi()

// Stato della mappa RFID
const rfidMap = ref({})
const loading = ref(false)
const ledEffects = ref([])

// Stato del form
const isEditing = ref(false)
const isScanning = ref(false)
const form = reactive({
  uid: '',
  type: 'audio',
  target: '',
  led: {
    enabled: false,
    effect_id: 'solid',
    color: '#ffffff',
    brightness: 70,
    speed: 30,
  }
})

// 1. Carica le associazioni dal server
async function loadRfidMap() {
  loading.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/rfid/map'))
    rfidMap.value = data || {}
  } catch (e) {
    console.error('Errore caricamento RFID:', extractApiError(e))
  } finally {
    loading.value = false
  }
}

async function loadLedEffects() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/led/effects'))
    ledEffects.value = data?.effects || []
  } catch (e) {
    console.error('Errore caricamento effetti LED:', extractApiError(e))
  }
}

// 2. Salva o Aggiorna un'associazione
async function saveMapping() {
  if (!form.uid.trim() || !form.target.trim()) return
  try {
    const api = getApi()
    const payload = {
      uid: form.uid,
      type: form.type,
      target: form.target,
      led: form.led.enabled ? { ...form.led } : undefined,
    }
    await guardedCall(() => api.post('/rfid/map', payload))
    alert('Associazione salvata con successo!')
    resetForm()
    await loadRfidMap()
  } catch (e) {
    alert(extractApiError(e, 'Errore salvataggio associazione'))
  }
}

// 3. Elimina un'associazione
async function deleteMapping(uid) {
  if (!confirm(`Vuoi davvero eliminare la statuina ${uid}?`)) return
  try {
    const api = getApi()
    // Potrebbe essere implementato come DELETE o POST in base al tuo backend
    await guardedCall(() => api.post('/rfid/delete', { uid }))
    await loadRfidMap()
  } catch (e) {
    alert(extractApiError(e, 'Errore eliminazione'))
  }
}

// 4. Gestione UI (Modifica e Reset)
function editMapping(uid, data) {
  isEditing.value = true
  form.uid = uid
  form.type = data.type || 'audio'
  form.target = data.target || ''
  if (data.led) {
    form.led = { ...form.led, ...data.led }
  } else {
    form.led = { enabled: false, effect_id: 'solid', color: '#ffffff', brightness: 70, speed: 30 }
  }
}

function resetForm() {
  isEditing.value = false
  isScanning.value = false
  form.uid = ''
  form.type = 'audio'
  form.target = ''
  form.led = { enabled: false, effect_id: 'solid', color: '#ffffff', brightness: 70, speed: 30 }
}

// 5. Scansione live tramite Socket.io
function waitForScan() {
  isScanning.value = true
  form.uid = ''
  // Il Socket.io avviserà quando il backend Python leggerà una carta fisica (Richiesta #2)
  alert('Appoggia una statuina sul lettore GufoBox. (Richiede l\'implementazione del driver Python)')
}

function handleSocketEvent(data) {
  // Se riceviamo un evento "rfid_scanned" mentre stiamo aspettando...
  if (isScanning.value && data?.uid) {
    form.uid = data.uid
    isScanning.value = false
  }
}

onMounted(() => {
  loadRfidMap()
  loadLedEffects()
  const socket = getSocket()
  if (socket) {
    socket.on('rfid_scanned', handleSocketEvent)
  }
})

onBeforeUnmount(() => {
  const socket = getSocket()
  if (socket) {
    socket.off('rfid_scanned', handleSocketEvent)
  }
})
</script>

<style scoped>
.admin-rfid {
  display: flex;
  flex-direction: column;
  gap: 25px;
}

.rfid-header h2 {
  margin: 0;
  color: #fff;
}

.rfid-header p {
  color: #aaa;
  margin: 5px 0 0 0;
}

.rfid-form-card, .rfid-list-card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.rfid-form-card h3, .rfid-list-card h3 {
  margin-top: 0;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
  color: #ffd27b;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 15px;
  margin-bottom: 20px;
}

@media (min-width: 768px) {
  .form-grid {
    grid-template-columns: 1fr 1fr 2fr;
  }
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-size: 0.9rem;
  color: #ccc;
  font-weight: bold;
}

.form-group input, .form-group select {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  color: white;
  padding: 10px;
  border-radius: 8px;
  font-size: 1rem;
}

.uid-input-group {
  display: flex;
  gap: 5px;
}

.uid-input-group input {
  flex: 1;
}

.btn-scan {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 0 15px;
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
}

.btn-scan.scanning {
  background: #ff9800;
  animation: pulse 1s infinite alternate;
}

@keyframes pulse {
  from { opacity: 1; }
  to { opacity: 0.7; }
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 15px;
}

.btn-save {
  background: #4caf50;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
}

.btn-save:disabled {
  background: #555;
  color: #888;
  cursor: not-allowed;
}

.btn-cancel {
  background: transparent;
  color: #ccc;
  border: 1px solid #555;
  padding: 10px 20px;
  border-radius: 8px;
  cursor: pointer;
}

/* Lista RFID */
.rfid-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 15px;
}

.rfid-item {
  background: #1e1e26;
  border: 1px solid #3a3a48;
  border-radius: 10px;
  padding: 15px;
  display: flex;
  align-items: center;
  gap: 15px;
  transition: transform 0.2s;
}

.rfid-item:hover {
  transform: translateY(-2px);
  border-color: #3f51b5;
}

.rfid-icon {
  font-size: 2rem;
  background: #2a2a35;
  width: 50px;
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
}

.rfid-info {
  flex: 1;
  overflow: hidden;
}

.rfid-info h4 {
  margin: 0 0 5px 0;
  color: #fff;
}

.target-path {
  margin: 0;
  font-size: 0.85rem;
  color: #aaa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rfid-actions {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.btn-icon {
  background: #2a2a35;
  border: none;
  border-radius: 6px;
  padding: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-icon:hover {
  background: #3a3a48;
}

.text-red {
  color: #ff4d4d;
}

.empty-state {
  text-align: center;
  padding: 30px;
  color: #aaa;
  font-style: italic;
}

/* Sezione LED */
.led-section {
  margin-top: 15px;
  border: 1px solid #3a3a48;
  border-radius: 8px;
  overflow: hidden;
}

.led-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 15px;
  background: #1e1e26;
  cursor: pointer;
  user-select: none;
}

.led-toggle:hover {
  background: #2a2a35;
}

.toggle-indicator {
  font-size: 0.8rem;
  font-weight: bold;
  padding: 3px 10px;
  border-radius: 20px;
  background: #555;
  color: #aaa;
}

.toggle-indicator.on {
  background: #4caf50;
  color: #fff;
}

.led-config {
  padding: 15px;
  background: #1e1e26;
}

.led-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.led-row input[type="range"] {
  width: 100%;
  background: transparent;
}

.led-row input[type="color"] {
  width: 100%;
  height: 38px;
  padding: 2px;
  border-radius: 6px;
  border: 1px solid #3a3a48;
  background: #1e1e26;
  cursor: pointer;
}

/* Badge LED nella lista */
.led-badge {
  margin: 4px 0 0 0;
  font-size: 0.8rem;
  color: #ffd27b;
  display: flex;
  align-items: center;
  gap: 6px;
}

.color-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1px solid #555;
}
</style>

