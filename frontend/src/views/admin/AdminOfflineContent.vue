<template>
  <div class="admin-offline-content">

    <div class="header-section">
      <h2>📴 Contenuti Offline</h2>
      <p>Genera contenuti audio offline usando Piper TTS per ogni modalità. I contenuti vengono
        riprodotti automaticamente quando manca la connessione internet.</p>
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- Connectivity status -->
    <div class="card connectivity-card">
      <div class="connectivity-row">
        <span class="connectivity-label">Stato connettività:</span>
        <span class="connectivity-badge" :class="online ? 'badge-online' : 'badge-offline'">
          {{ online ? '🟢 Online' : '🔴 Offline' }}
        </span>
      </div>
    </div>

    <!-- Note informative -->
    <div class="card note-card">
      <p class="note-text">
        ℹ️ I contenuti vengono generati con la voce Piper configurata.
        Assicurati di aver installato Piper e una voce italiana prima di procedere.
        Vai su <strong>Voce offline (Piper)</strong> per configurare la voce.
      </p>
    </div>

    <!-- Azioni globali -->
    <div class="card">
      <div class="global-actions">
        <button
          class="btn-generate-all"
          @click="generateAll"
          :disabled="generating"
        >
          {{ generating ? '⏳ Generazione in corso...' : '🔄 Genera tutti i contenuti' }}
        </button>
        <button class="btn-secondary" @click="loadContent" :disabled="loadingContent">
          🔄 Aggiorna lista
        </button>
      </div>

      <!-- Progress bar -->
      <div v-if="generating" class="progress-container">
        <div class="progress-info">
          <span>{{ progressLabel }}</span>
          <span>{{ generationStatus.progress }} / {{ generationStatus.total }}</span>
        </div>
        <div class="progress-bar-outer">
          <div
            class="progress-bar-inner"
            :style="{ width: progressPercent + '%' }"
          ></div>
        </div>
      </div>
    </div>

    <!-- Tabella modalità -->
    <div class="card">
      <h3>Modalità disponibili</h3>
      <div v-if="loadingContent" class="loading-text">Caricamento... ⏳</div>
      <div v-else class="modes-table">
        <div class="table-header">
          <span>Modalità</span>
          <span>Template</span>
          <span>File presenti</span>
          <span>Azioni</span>
        </div>
        <div
          v-for="mode in modeList"
          :key="mode.key"
          class="table-row"
        >
          <span class="mode-name">
            <span class="mode-icon">{{ mode.icon }}</span>
            {{ mode.label }}
          </span>
          <span class="mode-templates">{{ mode.templates }}</span>
          <span class="mode-count" :class="mode.count > 0 ? 'count-ok' : 'count-empty'">
            {{ mode.count > 0 ? `${mode.count} file` : '—' }}
          </span>
          <span class="mode-actions">
            <button
              class="btn-sm btn-generate"
              @click="generateMode(mode.key)"
              :disabled="generating"
              :title="`Genera contenuti per ${mode.label}`"
            >
              🔄 Genera
            </button>
            <button
              class="btn-sm btn-delete"
              @click="deleteMode(mode.key)"
              :disabled="generating || mode.count === 0"
              :title="`Elimina contenuti di ${mode.label}`"
            >
              🗑️ Elimina
            </button>
          </span>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

const online = ref(navigator.onLine)
const loadingContent = ref(false)
const generating = ref(false)
const contentData = ref({})

const generationStatus = reactive({
  running: false,
  progress: 0,
  total: 0,
  current_mode: '',
  generated: 0,
  skipped: 0,
  errors: [],
})

// ── Descrizioni modalità ──────────────────────────────────────────────────

const MODE_META = {
  spoken_quiz:        { label: 'Quiz Parlanti',        icon: '🎤', templates: 15 },
  adventure:          { label: 'Avventura',             icon: '🗺️', templates: 8 },
  personalized_story: { label: 'Favole Personalizzate', icon: '📖', templates: 6 },
  guess_sound:        { label: 'Indovina il Suono',     icon: '🔊', templates: 10 },
  imitate:            { label: 'Imita',                 icon: '🎭', templates: 8 },
  playful_english:    { label: 'Inglese Giocoso',       icon: '🇬🇧', templates: 8 },
  logic_games:        { label: 'Giochi Logici',         icon: '🧩', templates: 8 },
  entertainment:      { label: 'Intrattenimento',       icon: '🎮', templates: 4 },
  school:             { label: 'Scuola',                icon: '🏫', templates: 4 },
  ai_chat:            { label: 'Chat Gufetto',          icon: '🦉', templates: 4 },
  edu_ai:             { label: 'AI Educativa',          icon: '🎓', templates: 4 },
}

const modeList = computed(() => {
  return Object.entries(MODE_META).map(([key, meta]) => ({
    key,
    label: meta.label,
    icon: meta.icon,
    templates: meta.templates,
    count: contentData.value[key]?.count ?? 0,
  }))
})

const progressPercent = computed(() => {
  if (!generationStatus.total) return 0
  return Math.round((generationStatus.progress / generationStatus.total) * 100)
})

const progressLabel = computed(() => {
  if (generationStatus.current_mode) {
    const meta = MODE_META[generationStatus.current_mode]
    return `Generazione: ${meta ? meta.label : generationStatus.current_mode}...`
  }
  return 'Generazione in corso...'
})

// ── Connettività ──────────────────────────────────────────────────────────

function onOnline()  { online.value = true  }
function onOffline() { online.value = false }

// ── Polling stato generazione ─────────────────────────────────────────────

let _pollTimer = null

function startPolling() {
  if (_pollTimer) return
  _pollTimer = setInterval(pollStatus, 1500)
}

function stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer)
    _pollTimer = null
  }
}

async function pollStatus() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/offline/generate/status'))
    Object.assign(generationStatus, data)
    if (!data.running) {
      generating.value = false
      stopPolling()
      await loadContent()
      if (data.errors && data.errors.length) {
        showError(`Generazione completata con ${data.errors.length} errori.`)
      } else {
        showSuccess(`Generazione completata! ${data.generated} file creati, ${data.skipped} saltati.`)
      }
    }
  } catch {
    // ignora errori di polling
  }
}

// ── Caricamento contenuti ─────────────────────────────────────────────────

async function loadContent() {
  loadingContent.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/offline/content'))
    contentData.value = data
  } catch (e) {
    showError(extractApiError(e, 'Errore caricamento contenuti'))
  } finally {
    loadingContent.value = false
  }
}

// ── Generazione ───────────────────────────────────────────────────────────

async function startGeneration(modes, force = false) {
  if (generating.value) return
  clearFeedback()
  generating.value = true
  generationStatus.progress = 0
  generationStatus.total = 0
  generationStatus.current_mode = ''
  generationStatus.errors = []

  try {
    const api = getApi()
    await guardedCall(() => api.post('/offline/generate', { modes, force }))
    startPolling()
  } catch (e) {
    generating.value = false
    const msg = extractApiError(e, 'Errore avvio generazione')
    showError(msg)
  }
}

async function generateAll() {
  await startGeneration(null, false)
}

async function generateMode(mode) {
  await startGeneration([mode], true)
}

// ── Eliminazione ──────────────────────────────────────────────────────────

async function deleteMode(mode) {
  const meta = MODE_META[mode]
  if (!confirm(`Eliminare tutti i contenuti offline di "${meta?.label ?? mode}"?`)) return
  clearFeedback()
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.delete(`/offline/content/${mode}`))
    showSuccess(`Eliminati ${data.deleted} file per "${meta?.label ?? mode}".`)
    await loadContent()
  } catch (e) {
    showError(extractApiError(e, 'Errore eliminazione'))
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────

onMounted(() => {
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  loadContent()
})

onUnmounted(() => {
  window.removeEventListener('online', onOnline)
  window.removeEventListener('offline', onOffline)
  stopPolling()
})
</script>

<style scoped>
.admin-offline-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p  { color: #aaa; margin: 5px 0 0 0; }

.banner {
  padding: 12px 16px;
  border-radius: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.95rem;
  gap: 10px;
}
.banner-error   { background: #3b1212; color: #ef9a9a; border: 1px solid #c62828; }
.banner-success { background: #1b3a1b; color: #a5d6a7; border: 1px solid #388e3c; }
.banner-warning { background: #3b2e0a; color: #ffe082; border: 1px solid #f9a825; }
.banner-close   { background: none; border: none; cursor: pointer; opacity: 0.7; color: inherit; font-size: 1rem; padding: 0 4px; }
.banner-close:hover { opacity: 1; }

.card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.card h3 {
  margin-top: 0;
  color: #ffd27b;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
  margin-bottom: 15px;
}

.connectivity-card { padding: 14px 20px; }
.connectivity-row  { display: flex; align-items: center; gap: 12px; }
.connectivity-label { color: #aaa; font-size: 0.9rem; }
.connectivity-badge { font-weight: bold; font-size: 0.95rem; padding: 4px 12px; border-radius: 20px; }
.badge-online  { background: #1b3a1b; color: #a5d6a7; border: 1px solid #388e3c; }
.badge-offline { background: #3b1212; color: #ef9a9a; border: 1px solid #c62828; }

.note-card  { padding: 14px 20px; }
.note-text  { margin: 0; font-size: 0.88rem; color: #bbb; line-height: 1.6; }
.note-text strong { color: #ffd27b; }

.global-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 0;
}

.btn-generate-all {
  background: #4caf50;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
  font-size: 0.95rem;
}
.btn-generate-all:disabled { background: #555; color: #888; cursor: not-allowed; }
.btn-generate-all:hover:not(:disabled) { background: #43a047; }

.btn-secondary {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 8px 15px;
  border-radius: 8px;
  cursor: pointer;
}
.btn-secondary:disabled { color: #555; cursor: not-allowed; }

.progress-container {
  margin-top: 16px;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
  color: #bbb;
  margin-bottom: 6px;
}

.progress-bar-outer {
  background: #1e1e26;
  border-radius: 8px;
  height: 12px;
  overflow: hidden;
}

.progress-bar-inner {
  background: #4caf50;
  height: 100%;
  border-radius: 8px;
  transition: width 0.4s ease;
}

.loading-text { color: #aaa; font-style: italic; }

.modes-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.table-header {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 2fr;
  gap: 8px;
  padding: 8px 12px;
  font-size: 0.8rem;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid #3a3a48;
  margin-bottom: 4px;
}

.table-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 2fr;
  gap: 8px;
  padding: 10px 12px;
  background: #1e1e26;
  border-radius: 8px;
  align-items: center;
  font-size: 0.9rem;
}

.mode-name    { display: flex; align-items: center; gap: 8px; color: #ddd; font-weight: 500; }
.mode-icon    { font-size: 1.1rem; }
.mode-templates { color: #aaa; text-align: center; }
.mode-count   { text-align: center; font-weight: bold; }
.count-ok     { color: #a5d6a7; }
.count-empty  { color: #888; }

.mode-actions { display: flex; gap: 6px; flex-wrap: wrap; }

.btn-sm {
  padding: 5px 10px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 500;
}
.btn-sm:disabled { background: #444; color: #777; cursor: not-allowed; }

.btn-generate { background: #1565c0; color: white; }
.btn-generate:hover:not(:disabled) { background: #1976d2; }

.btn-delete   { background: #b71c1c; color: white; }
.btn-delete:hover:not(:disabled) { background: #c62828; }
</style>
