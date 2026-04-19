<template>
  <div class="story-studio">
    <!-- Header -->
    <div class="header-section">
      <div class="header-icon">🎬</div>
      <div>
        <h1 class="header-title">Story Studio</h1>
        <p class="header-sub">Crea storie audio professionali con intelligenza artificiale</p>
      </div>
    </div>

    <!-- FORM: Crea nuova storia -->
    <div class="card">
      <h2 class="card-title">✨ Crea Nuova Storia</h2>

      <div class="form-group">
        <label>Titolo *</label>
        <input v-model="form.title" type="text" class="input-field"
               placeholder="Es: Il Draghetto Timido" maxlength="200" />
      </div>

      <div class="form-group">
        <label>Spunto / Idea *</label>
        <textarea v-model="form.prompt" class="input-field textarea"
                  placeholder="Descrivi la tua storia: personaggi, ambientazione, avventura..."
                  rows="4" maxlength="2000"></textarea>
        <span class="char-count">{{ form.prompt.length }}/2000</span>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label>Fascia d'Età</label>
          <select v-model="form.age_group" class="input-field">
            <option value="bambino">🧸 Bambino (3-8 anni)</option>
            <option value="ragazzo">🎒 Ragazzo (9-14 anni)</option>
            <option value="adulto">👤 Adulto</option>
          </select>
        </div>
        <div class="form-group">
          <label>Durata</label>
          <select v-model="form.duration" class="input-field">
            <option value="short">⚡ Breve (5-7 min)</option>
            <option value="medium">📖 Media (10-15 min)</option>
            <option value="long">📚 Lunga (20-25 min)</option>
            <option value="extra">🎬 Extra (30-35 min)</option>
          </select>
        </div>
        <div class="form-group">
          <label>Voce Narratore</label>
          <select v-model="form.narrator_voice" class="input-field">
            <option v-for="v in voices" :key="v.id" :value="v.id">{{ v.label }}</option>
          </select>
        </div>
      </div>

      <div class="form-row checkbox-row">
        <label class="checkbox-label">
          <input type="checkbox" v-model="form.enable_music" />
          🎵 Musica di sottofondo
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="form.enable_sfx" />
          🔊 Effetti sonori
        </label>
      </div>

      <!-- Personaggi (espandibile) -->
      <div class="characters-section">
        <button class="btn-outline" @click="showCharacters = !showCharacters">
          {{ showCharacters ? '▲' : '▼' }} Personaggi personalizzati (opzionale)
        </button>
        <div v-if="showCharacters" class="characters-list">
          <div v-for="(char, idx) in form.characters" :key="idx" class="character-row">
            <input v-model="char.name" type="text" class="input-field char-name"
                   placeholder="Nome personaggio" maxlength="80" />
            <select v-model="char.voice" class="input-field char-voice">
              <option v-for="v in voices" :key="v.id" :value="v.id">{{ v.label }}</option>
            </select>
            <button class="btn-danger-sm" @click="removeCharacter(idx)">🗑️</button>
          </div>
          <button v-if="form.characters.length < 8" class="btn-outline add-char-btn"
                  @click="addCharacter">+ Aggiungi personaggio</button>
        </div>
      </div>

      <button class="btn-primary btn-generate"
              :disabled="!canGenerate || generating"
              @click="generateStory">
        <span v-if="generating">⏳ Generazione in corso...</span>
        <span v-else>🎬 Genera Storia</span>
      </button>
    </div>

    <!-- PROGRESS -->
    <div v-if="generating || activeProgress" class="card progress-card">
      <h2 class="card-title">⏳ Generazione in corso</h2>
      <div class="progress-steps">
        <div v-for="step in progressSteps" :key="step.phase"
             class="progress-step" :class="stepClass(step.phase)">
          <span class="step-icon">{{ step.icon }}</span>
          <span class="step-label">{{ step.label }}</span>
          <span v-if="currentPhase === step.phase" class="step-active-badge">in corso</span>
          <span v-if="isStepDone(step.phase)" class="step-done-badge">✓</span>
        </div>
      </div>
      <div class="progress-bar-outer">
        <div class="progress-bar-inner" :style="{ width: progressPct + '%' }"></div>
      </div>
      <p class="progress-message">{{ progressMessage }}</p>
      <button v-if="generating" class="btn-danger" @click="cancelGeneration">❌ Annulla</button>
    </div>

    <!-- LIBRERIA STORIE -->
    <div class="card">
      <div class="card-header-row">
        <h2 class="card-title">📚 Libreria Storie</h2>
        <button class="btn-outline" @click="loadStories" :disabled="loadingStories">
          {{ loadingStories ? '⏳' : '🔄' }} Aggiorna
        </button>
      </div>

      <div v-if="loadingStories" class="loading-msg">Caricamento storie...</div>
      <div v-else-if="stories.length === 0" class="empty-msg">
        Nessuna storia generata. Crea la tua prima storia! 🎭
      </div>
      <div v-else class="stories-grid">
        <div v-for="story in stories" :key="story.id" class="story-card"
             :class="'status-' + story.status">
          <div class="story-header">
            <span class="story-title">🎬 {{ story.title }}</span>
            <span class="story-status-badge" :class="story.status">
              {{ statusLabel(story.status) }}
            </span>
          </div>
          <div class="story-meta">
            <span v-if="story.duration_sec > 0">⏱️ {{ formatDuration(story.duration_sec) }}</span>
            <span>📅 {{ formatDate(story.created_at) }}</span>
            <span v-if="story.scene_count">🎭 {{ story.scene_count }} scene</span>
          </div>
          <div v-if="story.characters && story.characters.length" class="story-chars">
            <span v-for="c in story.characters" :key="c.name" class="char-badge">
              {{ c.name }}
            </span>
          </div>
          <div class="story-actions">
            <button v-if="story.status === 'completed'"
                    class="btn-sm btn-play"
                    @click="playStory(story)">▶️ Ascolta</button>
            <button v-if="story.status === 'completed'"
                    class="btn-sm btn-script"
                    @click="viewScript(story)">📋 Script</button>
            <button v-if="story.status === 'completed'"
                    class="btn-sm btn-download"
                    @click="downloadStory(story)">📥 Scarica</button>
            <button class="btn-sm btn-delete"
                    @click="confirmDelete(story)">🗑️ Elimina</button>
          </div>
        </div>
      </div>
    </div>

    <!-- PLAYER AUDIO (sticky) -->
    <div v-if="currentAudio" class="audio-player-bar">
      <div class="player-info">
        <span class="player-title">🎵 {{ currentAudio.title }}</span>
      </div>
      <audio ref="audioEl" controls autoplay class="audio-el"
             @ended="currentAudio = null">
        <source :src="currentAudio.url" type="audio/mpeg" />
      </audio>
      <button class="btn-sm btn-close-player" @click="currentAudio = null">✕</button>
    </div>

    <!-- MODALE SCRIPT -->
    <div v-if="scriptModal" class="modal-overlay" @click.self="scriptModal = null">
      <div class="modal-box">
        <div class="modal-header">
          <h3>📋 Script: {{ scriptModal.title }}</h3>
          <button @click="scriptModal = null">✕</button>
        </div>
        <div class="modal-body script-viewer">
          <div v-for="scene in (scriptModal.script || {}).scenes" :key="scene.scene_number"
               class="script-scene">
            <div class="scene-header">
              Scena {{ scene.scene_number }} — {{ scene.setting }}
              <span class="music-badge">🎵 {{ scene.music }}</span>
            </div>
            <div v-for="(line, li) in scene.lines" :key="li" class="script-line">
              <span class="line-char">{{ line.character }}:</span>
              <span v-if="line.sfx_before" class="sfx-tag">[{{ line.sfx_before }}]</span>
              <span class="line-text">{{ line.text }}</span>
              <span v-if="line.sfx_after" class="sfx-tag">[{{ line.sfx_after }}]</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- CONFERMA ELIMINA -->
    <div v-if="deleteTarget" class="modal-overlay" @click.self="deleteTarget = null">
      <div class="modal-box modal-small">
        <h3>🗑️ Elimina Storia</h3>
        <p>Sei sicuro di voler eliminare <strong>{{ deleteTarget.title }}</strong>?<br>
          Questa azione non può essere annullata.</p>
        <div class="modal-actions">
          <button class="btn-primary" @click="deleteTarget = null">Annulla</button>
          <button class="btn-danger" @click="doDelete">🗑️ Elimina</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { io } from 'socket.io-client'

const { apiUrl } = useApi()

// ---- Form ----
const form = ref({
  title: '',
  prompt: '',
  age_group: 'bambino',
  duration: 'medium',
  narrator_voice: 'nova',
  enable_music: true,
  enable_sfx: true,
  characters: [],
})
const showCharacters = ref(false)

// ---- Voices ----
const voices = ref([
  { id: 'nova',    label: 'Nova — Femminile calda' },
  { id: 'shimmer', label: 'Shimmer — Femminile dolce' },
  { id: 'fable',   label: 'Fable — Maschile narrativa' },
  { id: 'echo',    label: 'Echo — Maschile profonda' },
  { id: 'alloy',   label: 'Alloy — Neutra' },
  { id: 'onyx',    label: 'Onyx — Maschile grave' },
])

// ---- Stories ----
const stories = ref([])
const loadingStories = ref(false)

// ---- Progress ----
const generating = ref(false)
const currentStoryId = ref(null)
const currentPhase = ref(null)
const progressPct = ref(0)
const progressMessage = ref('')
const activeProgress = ref(false)

const progressSteps = [
  { phase: 'scripting',    icon: '📝', label: 'Generazione script (GPT-4)' },
  { phase: 'synthesizing', icon: '🎙️', label: 'Sintesi vocale' },
  { phase: 'sfx',          icon: '🔊', label: 'Effetti sonori e musiche' },
  { phase: 'mixing',       icon: '🎵', label: 'Mixaggio audio' },
  { phase: 'done',         icon: '✅', label: 'Completato!' },
]

const phaseOrder = progressSteps.map(s => s.phase)

function stepClass(phase) {
  const ci = phaseOrder.indexOf(currentPhase.value)
  const si = phaseOrder.indexOf(phase)
  if (si < ci) return 'done'
  if (si === ci) return 'active'
  return 'pending'
}
function isStepDone(phase) {
  const ci = phaseOrder.indexOf(currentPhase.value)
  const si = phaseOrder.indexOf(phase)
  return si < ci
}

// ---- Audio player ----
const currentAudio = ref(null)
const audioEl = ref(null)

// ---- Modals ----
const scriptModal = ref(null)
const deleteTarget = ref(null)

// ---- Socket ----
let socket = null

// ---- Computed ----
const canGenerate = computed(() =>
  form.value.title.trim().length > 0 && form.value.prompt.trim().length > 0
)

// ---- Lifecycle ----
onMounted(() => {
  loadStories()
  loadVoices()
  connectSocket()
})

onUnmounted(() => {
  if (socket) socket.disconnect()
})

// ---- Socket.IO ----
function connectSocket() {
  try {
    socket = io(apiUrl || window.location.origin, { transports: ['websocket', 'polling'] })
    socket.on('story_studio_progress', onProgress)
  } catch (e) {
    console.warn('Socket.IO non disponibile:', e)
  }
}

function onProgress(data) {
  if (currentStoryId.value && data.story_id !== currentStoryId.value) return
  currentPhase.value = data.phase
  progressPct.value = data.progress || 0
  progressMessage.value = data.message || ''
  activeProgress.value = true

  if (data.phase === 'done') {
    generating.value = false
    activeProgress.value = false
    loadStories()
  } else if (data.phase === 'error') {
    generating.value = false
    activeProgress.value = false
    alert('Errore durante la generazione: ' + data.message)
    loadStories()
  }
}

// ---- API ----
async function loadVoices() {
  try {
    const r = await fetch('/api/story-studio/voices')
    if (r.ok) {
      const data = await r.json()
      voices.value = data.map(v => ({ id: v.id, label: `${capitalize(v.id)} — ${v.label}` }))
    }
  } catch (_) {}
}

async function loadStories() {
  loadingStories.value = true
  try {
    const r = await fetch('/api/story-studio/stories')
    if (r.ok) stories.value = await r.json()
  } catch (e) {
    console.error('Errore caricamento storie:', e)
  } finally {
    loadingStories.value = false
  }
}

async function generateStory() {
  if (!canGenerate.value || generating.value) return
  generating.value = true
  activeProgress.value = true
  currentPhase.value = 'scripting'
  progressPct.value = 5
  progressMessage.value = 'Avvio generazione...'

  const chars = form.value.characters.filter(c => c.name.trim())
  const payload = {
    ...form.value,
    characters: chars.length ? chars : null,
  }

  try {
    const r = await fetch('/api/story-studio/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const data = await r.json()
    if (!r.ok) {
      generating.value = false
      activeProgress.value = false
      alert('Errore: ' + (data.error || 'Errore sconosciuto'))
      return
    }
    currentStoryId.value = data.story_id
  } catch (e) {
    generating.value = false
    activeProgress.value = false
    alert('Errore di rete: ' + e.message)
  }
}

function cancelGeneration() {
  generating.value = false
  activeProgress.value = false
  currentStoryId.value = null
  currentPhase.value = null
  progressPct.value = 0
  progressMessage.value = ''
}

async function playStory(story) {
  currentAudio.value = {
    title: story.title,
    url: `/api/story-studio/story/${story.id}/audio`,
  }
}

async function downloadStory(story) {
  const a = document.createElement('a')
  a.href = `/api/story-studio/story/${story.id}/audio`
  a.download = `${story.title}.mp3`
  a.click()
}

async function viewScript(story) {
  try {
    const r = await fetch(`/api/story-studio/story/${story.id}/script`)
    if (r.ok) {
      const script = await r.json()
      scriptModal.value = { title: story.title, script }
    }
  } catch (e) {
    alert('Impossibile caricare lo script')
  }
}

function confirmDelete(story) {
  deleteTarget.value = story
}

async function doDelete() {
  if (!deleteTarget.value) return
  try {
    const r = await fetch(`/api/story-studio/story/${deleteTarget.value.id}`, {
      method: 'DELETE',
    })
    if (r.ok) {
      deleteTarget.value = null
      loadStories()
    } else {
      const d = await r.json()
      alert('Errore: ' + (d.error || 'impossibile eliminare'))
    }
  } catch (e) {
    alert('Errore di rete: ' + e.message)
  }
}

function addCharacter() {
  form.value.characters.push({ name: '', voice: 'nova' })
}

function removeCharacter(idx) {
  form.value.characters.splice(idx, 1)
}

// ---- Helpers ----
function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function statusLabel(status) {
  const map = { completed: '✅ Completata', in_progress: '⏳ In generazione', error: '❌ Errore' }
  return map[status] || status
}

function formatDuration(sec) {
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })
  } catch (_) { return iso }
}
</script>

<style scoped>
.story-studio {
  padding: 1.5rem;
  max-width: 1100px;
  margin: 0 auto;
  padding-bottom: 120px;
}

.header-section {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.header-icon { font-size: 2.5rem; }
.header-title { font-size: 1.6rem; font-weight: 700; margin: 0; }
.header-sub { margin: 0; color: #aaa; font-size: 0.9rem; }

.card {
  background: #1c1c24;
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  border: 1px solid #2d2d3a;
}
.card-title { font-size: 1.15rem; font-weight: 600; margin: 0 0 1rem; }
.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.form-group { margin-bottom: 1rem; }
.form-group label { display: block; font-size: 0.85rem; color: #aaa; margin-bottom: 0.3rem; }
.input-field {
  width: 100%;
  background: #2a2a36;
  border: 1px solid #3d3d50;
  border-radius: 8px;
  color: #fff;
  padding: 0.55rem 0.75rem;
  font-size: 0.95rem;
  box-sizing: border-box;
}
.input-field:focus { outline: none; border-color: #6c63ff; }
.textarea { resize: vertical; min-height: 90px; font-family: inherit; }
.char-count { font-size: 0.75rem; color: #777; float: right; margin-top: 0.2rem; }

.form-row { display: flex; gap: 1rem; }
.form-row .form-group { flex: 1; }
.checkbox-row { align-items: center; gap: 2rem; }
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-size: 0.95rem;
  user-select: none;
}
.checkbox-label input { width: 16px; height: 16px; accent-color: #6c63ff; cursor: pointer; }

.characters-section { margin-top: 0.75rem; }
.characters-list { margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.5rem; }
.character-row { display: flex; gap: 0.5rem; align-items: center; }
.char-name { flex: 2; }
.char-voice { flex: 2; }
.add-char-btn { margin-top: 0.25rem; align-self: flex-start; }

.btn-primary {
  background: #6c63ff;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0.65rem 1.4rem;
  font-size: 0.95rem;
  cursor: pointer;
  font-weight: 600;
  transition: background 0.2s;
}
.btn-primary:hover:not(:disabled) { background: #5a51e0; }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }

.btn-generate { width: 100%; margin-top: 1rem; padding: 0.85rem; font-size: 1rem; }

.btn-outline {
  background: transparent;
  color: #aaa;
  border: 1px solid #3d3d50;
  border-radius: 8px;
  padding: 0.5rem 1rem;
  font-size: 0.88rem;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}
.btn-outline:hover:not(:disabled) { border-color: #6c63ff; color: #fff; }

.btn-danger {
  background: #e04444;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 0.6rem 1.2rem;
  font-size: 0.9rem;
  cursor: pointer;
}
.btn-danger:hover { background: #c73333; }

.btn-danger-sm {
  background: transparent;
  color: #e04444;
  border: 1px solid #e04444;
  border-radius: 6px;
  padding: 0.35rem 0.6rem;
  font-size: 0.85rem;
  cursor: pointer;
}

.btn-sm {
  border: none;
  border-radius: 6px;
  padding: 0.35rem 0.75rem;
  font-size: 0.82rem;
  cursor: pointer;
  font-weight: 500;
}
.btn-play     { background: #2e7d32; color: #fff; }
.btn-script   { background: #1565c0; color: #fff; }
.btn-download { background: #37474f; color: #fff; }
.btn-delete   { background: transparent; color: #e04444; border: 1px solid #e04444; }

/* Progress */
.progress-card { border-color: #6c63ff; }
.progress-steps { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
.progress-step {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.88rem;
  color: #777;
}
.progress-step.active { color: #6c63ff; font-weight: 600; }
.progress-step.done   { color: #4caf50; }
.step-active-badge {
  background: #6c63ff;
  color: #fff;
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 0.72rem;
}
.step-done-badge { color: #4caf50; font-weight: 700; }
.progress-bar-outer {
  background: #2a2a36;
  border-radius: 999px;
  height: 10px;
  overflow: hidden;
  margin-bottom: 0.6rem;
}
.progress-bar-inner {
  background: linear-gradient(90deg, #6c63ff, #4caf50);
  height: 100%;
  border-radius: 999px;
  transition: width 0.4s ease;
}
.progress-message { color: #aaa; font-size: 0.88rem; margin-bottom: 0.75rem; }

/* Stories grid */
.stories-grid { display: flex; flex-direction: column; gap: 0.75rem; }
.story-card {
  background: #23232f;
  border-radius: 10px;
  padding: 1rem;
  border-left: 4px solid #3d3d50;
}
.story-card.status-completed { border-left-color: #4caf50; }
.story-card.status-in_progress { border-left-color: #6c63ff; }
.story-card.status-error { border-left-color: #e04444; }
.story-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.4rem;
}
.story-title { font-weight: 600; font-size: 1rem; }
.story-status-badge {
  font-size: 0.78rem;
  padding: 2px 10px;
  border-radius: 999px;
  background: #2d2d3a;
}
.story-status-badge.completed   { background: #1b3a1c; color: #4caf50; }
.story-status-badge.in_progress { background: #1e1a3a; color: #9e8ffc; }
.story-status-badge.error       { background: #3a1a1a; color: #e04444; }
.story-meta { display: flex; gap: 1rem; color: #888; font-size: 0.82rem; margin-bottom: 0.4rem; }
.story-chars { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.5rem; }
.char-badge {
  background: #2d2d3a;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.78rem;
  color: #aaa;
}
.story-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }

.loading-msg, .empty-msg { color: #777; font-size: 0.9rem; text-align: center; padding: 1.5rem; }

/* Audio player (sticky) */
.audio-player-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #1c1c24;
  border-top: 1px solid #2d2d3a;
  padding: 0.75rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  z-index: 1000;
}
.player-info { min-width: 150px; }
.player-title { font-size: 0.9rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.audio-el { flex: 1; height: 36px; }
.btn-close-player {
  background: transparent;
  border: 1px solid #555;
  color: #aaa;
  border-radius: 6px;
  padding: 0.3rem 0.6rem;
  cursor: pointer;
}

/* Modals */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.7);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.modal-box {
  background: #1c1c24;
  border-radius: 14px;
  border: 1px solid #3d3d50;
  padding: 1.5rem;
  max-width: 800px;
  width: 100%;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.modal-small { max-width: 420px; }
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-header h3 { margin: 0; font-size: 1.1rem; }
.modal-header button {
  background: transparent;
  border: none;
  color: #aaa;
  font-size: 1.2rem;
  cursor: pointer;
}
.modal-body { overflow-y: auto; }
.modal-actions { display: flex; gap: 0.75rem; justify-content: flex-end; }

/* Script viewer */
.script-viewer { font-size: 0.88rem; }
.script-scene { margin-bottom: 1.25rem; }
.scene-header {
  font-weight: 600;
  color: #9e8ffc;
  margin-bottom: 0.4rem;
  display: flex;
  gap: 0.75rem;
  align-items: center;
}
.music-badge {
  font-size: 0.78rem;
  background: #2a2236;
  border-radius: 999px;
  padding: 2px 8px;
  color: #b39ddb;
}
.script-line {
  padding: 0.3rem 0.5rem;
  border-left: 2px solid #2d2d3a;
  margin-bottom: 0.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: baseline;
}
.line-char { font-weight: 700; color: #aaa; min-width: 100px; }
.line-text { color: #ddd; flex: 1; }
.sfx-tag { color: #888; font-size: 0.8rem; font-style: italic; }

@media (max-width: 640px) {
  .form-row { flex-direction: column; }
  .checkbox-row { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
  .progress-steps { flex-direction: column; gap: 0.5rem; }
}
</style>
