<template>
  <div class="admin-media">
    <div class="header-section">
      <h2>Libreria e Statuine 🎵</h2>
      <p>Esplora i tuoi file audio e associali alle statuine magiche.</p>
    </div>

    <div class="media-grid">
      
      <div class="rfid-section card">
        <h3>Statuine Associate</h3>
        
        <div v-if="loadingMap" class="loading">Caricamento statuine... ⏳</div>
        <div v-else-if="Object.keys(rfidMap).length === 0" class="empty">
          Nessuna statuina associata. Usa il pannello qui a fianco!
        </div>
        
        <ul v-else class="rfid-list">
          <li v-for="(data, uid) in rfidMap" :key="uid" class="rfid-item">
            <div class="rfid-info">
              <span class="uid-badge">{{ uid }}</span>
              <span class="target-path" :title="data.target">
                {{ getFileName(data.target) }}
              </span>
            </div>
            <button class="btn-delete" @click="deleteMapping(uid)" title="Rimuovi Associazione">🗑️</button>
          </li>
        </ul>
      </div>

      <div class="file-section card">
        <h3>Associa Nuova Statuina</h3>
        
        <div class="association-form">
          <div class="input-group">
            <label>Codice Statuina (UID)</label>
            <div class="uid-input-wrapper">
              <input type="text" v-model="newMapping.uid" placeholder="Es. 04:B2:A1:C3" />
              <p class="help-text">Appoggia una statuina per leggere il codice, o recitalo a mano.</p>
            </div>
          </div>
          
          <div class="input-group">
            <label>File Audio Selezionato</label>
            <input type="text" v-model="newMapping.target" readonly placeholder="Seleziona un file qui sotto ⬇️" class="readonly-input" />
          </div>
          
          <button class="btn-save" @click="saveMapping" :disabled="!newMapping.uid || !newMapping.target">
            🔗 Associa Statuina
          </button>
        </div>

        <hr class="divider" />

        <div class="file-browser-header">
          <h3>Sfoglia File</h3>
          <button class="btn-up" @click="goUp" :disabled="currentPath === defaultRoot">⬆️ Su</button>
        </div>

        <div v-if="loadingFiles" class="loading">Caricamento cartella... ⏳</div>
        
        <ul v-else class="file-list">
          <li 
            v-for="item in files" 
            :key="item.name" 
            class="file-item"
            @click="handleFileClick(item)"
          >
            <span class="icon">{{ item.is_dir ? '📁' : (item.type === 'audio' ? '🎵' : '📄') }}</span>
            <span class="name">{{ item.name }}</span>
            <button v-if="!item.is_dir" class="btn-select">Seleziona</button>
          </li>
        </ul>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

// Stato RFID
const rfidMap = ref({})
const loadingMap = ref(true)

// Stato File Manager
const files = ref([])
const currentPath = ref('')
const defaultRoot = ref('')
const loadingFiles = ref(true)

// Form nuova associazione
const newMapping = ref({ uid: '', target: '', type: 'audio' })

// --- GESTIONE RFID ---
async function loadRfidMap() {
  loadingMap.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/rfid/map'))
    rfidMap.value = data || {}
  } catch (e) {
    console.error("Errore caricamento RFID", e)
  } finally {
    loadingMap.value = false
  }
}

async function saveMapping() {
  try {
    const api = getApi()
    await guardedCall(() => api.post('/rfid/map', newMapping.value))
    alert("Statuina associata con successo! 🎉")
    newMapping.value = { uid: '', target: '', type: 'audio' }
    loadRfidMap()
  } catch (e) {
    alert(extractApiError(e, "Errore associazione"))
  }
}

async function deleteMapping(uid) {
  if (!confirm(`Seicuro di voler rimuovere la statuina ${uid}?`)) return
  try {
    const api = getApi()
    await guardedCall(() => api.post('/rfid/delete', { uid }))
    loadRfidMap()
  } catch (e) {
    alert("Errore eliminazione")
  }
}

// --- GESTIONE FILE MANAGER ---
async function loadFiles(path = '') {
  loadingFiles.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get(`/files/list?path=${encodeURIComponent(path)}`))
    files.value = data.entries
    currentPath.value = data.current_path
    if (!defaultRoot.value) defaultRoot.value = data.default_path
  } catch (e) {
    console.error("Errore caricamento file", e)
  } finally {
    loadingFiles.value = false
  }
}

function handleFileClick(item) {
  if (item.is_dir) {
    loadFiles(item.path)
  } else {
    // Se è un file, lo impostiamo come target nel form!
    newMapping.value.target = item.path
  }
}

function goUp() {
  // Rimuove l'ultima cartella dal percorso
  const parts = currentPath.value.split('/')
  parts.pop()
  loadFiles(parts.join('/'))
}

// Utility
function getFileName(path) {
  if (!path) return ''
  return path.split('/').pop()
}

onMounted(() => {
  loadRfidMap()
  loadFiles()
})
</script>

<style scoped>
.admin-media { display: flex; flex-direction: column; gap: 20px; }
.header-section h2 { margin: 0; color: #fff; }
.header-section p { color: #aaa; margin: 5px 0 0 0; }

.media-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

.card { background: #2a2a35; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
.card h3 { margin-top: 0; color: #ffd27b; border-bottom: 1px solid #3a3a48; padding-bottom: 10px; }

.loading, .empty { text-align: center; color: #888; padding: 20px 0; font-style: italic; }

/* Lista Statuine */
.rfid-list { list-style: none; padding: 0; margin: 0; }
.rfid-item { display: flex; justify-content: space-between; align-items: center; background: #1e1e26; padding: 10px 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #3a3a48; }
.rfid-info { display: flex; flex-direction: column; gap: 5px; overflow: hidden; }
.uid-badge { background: #3f51b5; color: white; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; width: fit-content; font-family: monospace; }
.target-path { color: #ccc; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.btn-delete { background: transparent; border: none; color: #ff4d4d; font-size: 1.2rem; cursor: pointer; transition: 0.2s; }
.btn-delete:hover { transform: scale(1.1); }

/* Form Associazione */
.input-group { display: flex; flex-direction: column; gap: 5px; margin-bottom: 15px; }
.input-group label { color: #fff; font-size: 0.9rem; font-weight: bold; }
.input-group input { background: #1e1e26; border: 1px solid #3a3a48; color: white; padding: 10px; border-radius: 8px; font-size: 1rem; }
.readonly-input { background: #1a1a20 !important; color: #4caf50 !important; cursor: not-allowed; }
.help-text { font-size: 0.8rem; color: #888; margin: 0; }

.btn-save { width: 100%; background: #4caf50; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: bold; font-size: 1rem; cursor: pointer; transition: 0.2s; }
.btn-save:disabled { background: #555; cursor: not-allowed; }

.divider { border: 0; height: 1px; background: #3a3a48; margin: 20px 0; }

/* File Browser */
.file-browser-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.btn-up { background: #3a3a48; color: white; border: none; padding: 5px 10px; border-radius: 6px; cursor: pointer; }

.file-list { list-style: none; padding: 0; margin: 0; max-height: 300px; overflow-y: auto; }
.file-item { display: flex; align-items: center; gap: 10px; padding: 10px; border-bottom: 1px solid #3a3a48; cursor: pointer; transition: 0.2s; }
.file-item:hover { background: #3a3a48; }
.file-item .icon { font-size: 1.2rem; }
.file-item .name { flex: 1; color: #ddd; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.btn-select { background: #3f51b5; color: white; border: none; padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; cursor: pointer; }

/* Mobile */
@media (max-width: 768px) {
  .media-grid { grid-template-columns: 1fr; }
}
</style>

