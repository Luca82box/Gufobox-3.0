<template>
  <div class="admin-media-statuine">

    <div class="ms-header">
      <h2>Media &amp; Statuine 🎵🏷️</h2>
      <p>Esplora cartelle e file, poi associali alle statuine magiche con tutte le opzioni avanzate.</p>
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- MAIN LAYOUT: split form + explorer -->
    <div class="ms-layout">

      <!-- ═══════════════════════════════════════
           LEFT PANEL: Profile form
      ═══════════════════════════════════════ -->
      <div class="ms-form-panel card">
        <h3>{{ isEditing ? '✏️ Modifica Profilo' : '➕ Nuovo Profilo Statuina' }}</h3>

        <div class="form-grid-2">
          <div class="form-group">
            <label>Codice RFID (UID)</label>
            <div class="uid-input-group">
              <input type="text" v-model="form.rfid_code" placeholder="Es. AA:BB:CC:DD" :disabled="isEditing" />
              <button class="btn-scan" @click="waitForScan" :class="{ scanning: isScanning }">
                {{ isScanning ? '📡 In ascolto...' : '🔍 Scansiona' }}
              </button>
            </div>
            <p v-if="isScanning" class="scan-hint">Avvicina la statuina al lettore RFID...</p>
          </div>
          <div class="form-group">
            <label>Nome</label>
            <input type="text" v-model="form.name" placeholder="Es. Principessa Bella" />
          </div>
          <div class="form-group">
            <label>Modalità</label>
            <select v-model="form.mode" @change="onModeChange">
              <option value="media_folder">🎵 Cartella Media</option>
              <option value="web_media">🌐 Contenuto Web (radio · podcast · YouTube · RSS)</option>
              <option value="ai_chat">🦉 Chat AI (Gufetto)</option>
              <option value="edu_ai">🎓 AI Educativa</option>
              <option value="school">🏫 Scuola (avvia wizard guidato)</option>
              <option value="entertainment">🎮 Intrattenimento (avvia wizard guidato)</option>
            </select>
          </div>
          <div class="form-group form-group-inline">
            <label>Abilitata</label>
            <input type="checkbox" v-model="form.enabled" class="checkbox-lg" />
          </div>
        </div>

        <!-- MEDIA FOLDER: path shown + explorer trigger -->
        <div v-if="form.mode === 'media_folder'" class="mode-section">
          <h4>🎵 Cartella / File Media</h4>
          <div class="selected-path-row">
            <div class="selected-path-display" :class="{ 'has-value': form.folder }">
              {{ form.folder || 'Nessuna selezione — usa l\'explorer →' }}
            </div>
            <button v-if="form.folder" class="btn-clear-path" @click="form.folder = ''" title="Rimuovi selezione">✕</button>
          </div>
          <p class="mode-hint">Naviga le cartelle nel pannello a destra e clicca <strong>Seleziona questa cartella</strong> o un file audio.</p>
          <div class="form-grid-2">
            <div class="form-group">
              <label>Volume {{ form.volume }}%</label>
              <input type="range" min="0" max="100" v-model.number="form.volume" />
            </div>
            <div class="form-group form-group-inline">
              <label>Loop</label>
              <input type="checkbox" v-model="form.loop" class="checkbox-lg" />
            </div>
          </div>
        </div>

        <!-- WEB MEDIA -->
        <div v-if="form.mode === 'web_media'" class="mode-section web-media-section">
          <h4>🌐 Contenuto Web</h4>
          <p class="mode-hint">Inserisci il link di una radio, podcast, video YouTube o feed RSS. MPV/yt-dlp gestiranno automaticamente la riproduzione.</p>
          <div class="form-grid-2">
            <div class="form-group form-group-full">
              <label>URL / Link Web</label>
              <input type="url" v-model="form.web_media_url" placeholder="https://... (radio, podcast, YouTube, RSS)" />
            </div>
            <div class="form-group">
              <label>Tipo contenuto</label>
              <select v-model="form.web_content_type">
                <option value="radio">📻 Radio streaming</option>
                <option value="podcast">🎙️ Podcast</option>
                <option value="youtube">▶️ YouTube</option>
                <option value="rss">📰 Feed RSS</option>
                <option value="generic">🌍 Web media generico</option>
              </select>
            </div>
            <div class="form-group">
              <label>Volume {{ form.volume }}%</label>
              <input type="range" min="0" max="100" v-model.number="form.volume" />
            </div>
            <div v-if="form.web_content_type === 'rss'" class="form-group">
              <label>Limite articoli: {{ form.rss_limit }}</label>
              <input type="range" min="1" max="50" v-model.number="form.rss_limit" />
            </div>
          </div>
        </div>

        <!-- AI CHAT -->
        <div v-if="form.mode === 'ai_chat'" class="mode-section">
          <h4>🦉 Chat AI (Gufetto)</h4>
          <div class="form-group form-group-full">
            <label>Prompt extra (opzionale)</label>
            <textarea v-model="form.ai_prompt" rows="3" placeholder="Es. Sei un pirata gentile..."></textarea>
          </div>
        </div>

        <!-- EDU AI -->
        <div v-if="form.mode === 'edu_ai'" class="mode-section edu-ai-section">
          <h4>🎓 AI Educativa</h4>
          <p class="mode-hint">Quando questa statuina viene avvicinata, attiverà la modalità educativa configurata qui sotto.</p>
          <div class="form-grid-2">
            <div class="form-group">
              <label>Fascia d'Età</label>
              <select v-model="form.edu_config.age_group">
                <option value="bambino">🧒 Bambino (3–7 anni)</option>
                <option value="ragazzo">👦 Ragazzo (8–13 anni)</option>
                <option value="adulto">👨 Adulto / Genitore</option>
              </select>
            </div>
            <div class="form-group">
              <label>Modalità Attività</label>
              <select v-model="form.edu_config.activity_mode">
                <option value="free_conversation">💬 Conversazione Libera</option>
                <option value="teaching_general">📚 Insegnamento Generale</option>
                <option value="interactive_story">📖 Storia Interattiva</option>
                <option value="animal_sounds_games">🦁 Animali e Versi</option>
                <option value="quiz">❓ Quiz</option>
                <option value="math">🧮 Matematica</option>
                <option value="foreign_languages">🌍 Lingue Straniere</option>
              </select>
            </div>
            <div class="form-group" v-if="form.edu_config.activity_mode === 'foreign_languages'">
              <label>Lingua da Imparare</label>
              <select v-model="form.edu_config.language_target">
                <option value="english">🇬🇧 Inglese</option>
                <option value="spanish">🇪🇸 Spagnolo</option>
                <option value="german">🇩🇪 Tedesco</option>
                <option value="french">🇫🇷 Francese</option>
                <option value="japanese">🇯🇵 Giapponese</option>
                <option value="chinese">🇨🇳 Cinese</option>
              </select>
            </div>
            <div class="form-group">
              <label>Step (1–10): {{ form.edu_config.learning_step }}</label>
              <input type="range" min="1" max="10" step="1" v-model.number="form.edu_config.learning_step" />
            </div>
          </div>
          <div class="edu-summary">
            <span class="edu-tag">{{ eduSummary }}</span>
          </div>
        </div>

        <!-- WIZARD modes -->
        <div v-if="form.mode === 'school' || form.mode === 'entertainment'" class="mode-section wizard-mode-section">
          <h4>{{ form.mode === 'school' ? '🏫 Modalità Scuola' : '🎮 Modalità Intrattenimento' }}</h4>
          <div class="wizard-mode-info">
            <p>
              Questa statuina <strong>avvia un wizard guidato</strong> che chiede all'utente:<br/>
              fascia d'età → attività → (lingua) → (livello)
            </p>
            <p>
              Non è necessario configurare opzioni aggiuntive qui. Le attività disponibili
              si configurano nella sezione <em>AI → Categorie Wizard</em>.
            </p>
          </div>
        </div>

        <!-- Immagine statuina -->
        <div class="form-group" style="margin-bottom:15px">
          <label>Immagine Statuina (percorso, opzionale)</label>
          <input type="text" v-model="form.image_path" placeholder="/home/gufobox/media/immagini/bella.png" />
        </div>

        <!-- LED effects -->
        <div class="led-section">
          <div class="led-toggle" @click="form.led.enabled = !form.led.enabled">
            <span>💡 Effetto LED per questa statuina</span>
            <span class="toggle-indicator" :class="{ on: form.led.enabled }">{{ form.led.enabled ? 'ON' : 'OFF' }}</span>
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

        <p v-if="saveError" class="form-error">{{ saveError }}</p>
        <div class="form-actions">
          <button v-if="isEditing" class="btn-cancel" @click="resetForm">Annulla</button>
          <button class="btn-save" @click="saveProfile" :disabled="!form.rfid_code.trim() || !form.name.trim() || isSaving">
            {{ isSaving ? '⏳ Salvataggio...' : '💾 Salva Profilo' }}
          </button>
        </div>
      </div>

      <!-- ═══════════════════════════════════════
           RIGHT PANEL: Folder Explorer
           (always visible to browse and select)
      ═══════════════════════════════════════ -->
      <div class="ms-explorer-panel card">
        <div class="explorer-header">
          <h3>📁 Explorer Media</h3>
          <div class="explorer-nav-bar">
            <button class="btn-nav" @click="goUp" :disabled="currentPath === defaultRoot" title="Su">⬆️</button>
            <button class="btn-nav" @click="loadFiles(defaultRoot)" :disabled="currentPath === defaultRoot" title="Home">🏠</button>
            <span class="breadcrumb-path" :title="currentPath">{{ shortPath(currentPath) }}</span>
          </div>
        </div>

        <!-- Select current folder button (only in media_folder mode) -->
        <div v-if="form.mode === 'media_folder'" class="select-folder-bar">
          <button class="btn-select-folder" @click="selectCurrentFolder">
            📂 Seleziona questa cartella
          </button>
        </div>

        <div v-if="loadingFiles" class="explorer-loading">Caricamento... ⏳</div>

        <ul v-else class="explorer-list">
          <li
            v-for="item in browserFiles"
            :key="item.name"
            class="explorer-item"
            :class="{ 'is-dir': item.is_dir, 'is-selected': form.folder === item.path }"
            @click="handleExplorerClick(item)"
          >
            <span class="ex-icon">{{ item.is_dir ? '📁' : (item.type === 'audio' ? '🎵' : '📄') }}</span>
            <span class="ex-name">{{ item.name }}</span>
            <span v-if="!item.is_dir && form.mode === 'media_folder'" class="ex-select-hint">
              {{ form.folder === item.path ? '✅' : 'Seleziona' }}
            </span>
          </li>
          <li v-if="browserFiles.length === 0" class="explorer-empty">
            Cartella vuota
          </li>
        </ul>

        <!-- Current RFID state -->
        <div v-if="currentRfid" class="current-card">
          <h4>▶️ In Riproduzione</h4>
          <div class="current-grid">
            <div><span class="label">RFID:</span> {{ currentRfid.current_rfid }}</div>
            <div><span class="label">Profilo:</span> {{ currentRfid.current_profile_name }}</div>
            <div><span class="label">Modalità:</span> {{ currentRfid.current_mode }}</div>
            <div v-if="currentRfid.web_content_type"><span class="label">Tipo Web:</span> {{ currentRfid.web_content_type }}</div>
            <div v-if="currentRfid.current_media_path"><span class="label">File:</span> {{ currentRfid.current_media_path }}</div>
          </div>
        </div>
      </div>

    </div>

    <!-- ═══════════════════════════════════════
         PROFILES LIST
    ═══════════════════════════════════════ -->
    <div class="rfid-list-card card">
      <div class="list-header">
        <h3>Profili Configurati</h3>
        <button class="btn-refresh" @click="loadProfiles">🔄</button>
      </div>
      <div v-if="loading" class="loading-state">Caricamento... ⏳</div>
      <div v-else-if="profiles.length === 0" class="empty-state">
        Nessun profilo configurato. Usa il form qui sopra per aggiungere la prima statuina.
      </div>
      <div v-else class="rfid-grid">
        <div
          v-for="p in profiles"
          :key="p.rfid_code"
          class="rfid-item"
          :class="{ active: currentRfid?.current_rfid === p.rfid_code, disabled: !p.enabled }"
        >
          <div class="rfid-icon">{{ modeIcon(p.mode) }}</div>
          <div class="rfid-info">
            <h4>{{ p.name }}</h4>
            <p class="uid-code">{{ p.rfid_code }}</p>
            <p class="mode-badge" :class="p.mode">{{ modeLabel(p.mode) }}</p>
            <p class="target-path">{{ profileTarget(p) }}</p>
            <p v-if="p.led?.enabled" class="led-badge">💡 {{ p.led.effect_id }} <span class="color-dot" :style="{ background: p.led.color }"></span></p>
            <p v-if="!p.enabled" class="disabled-badge">⛔ Disabilitata</p>
          </div>
          <div class="rfid-actions">
            <button class="btn-icon" @click="editProfile(p)" title="Modifica">✏️</button>
            <button class="btn-icon btn-trigger" @click="triggerProfile(p.rfid_code)" title="Trigger" :disabled="!p.enabled">▶️</button>
            <button class="btn-icon text-red" @click="deleteProfile(p.rfid_code)" title="Elimina">🗑️</button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, getSocket, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

// ─── Profile state ─────────────────────────────────────────
const profiles = ref([])
const loading = ref(false)
const isSaving = ref(false)
const saveError = ref('')
const isEditing = ref(false)
const isScanning = ref(false)
const ledEffects = ref([])
const currentRfid = ref(null)

// ─── File browser state ────────────────────────────────────
const browserFiles = ref([])
const currentPath = ref('')
const defaultRoot = ref('')
const loadingFiles = ref(true)

// ─── Form ──────────────────────────────────────────────────
const EDU_CONFIG_DEFAULT = () => ({
  age_group: 'bambino',
  activity_mode: 'free_conversation',
  language_target: 'english',
  learning_step: 1,
})

const FORM_DEFAULT = () => ({
  rfid_code: '', name: '', enabled: true, mode: 'media_folder',
  image_path: '', folder: '', web_media_url: '', web_content_type: 'generic',
  ai_prompt: '', rss_limit: 10, volume: 70, loop: true,
  edu_config: EDU_CONFIG_DEFAULT(),
  led: { enabled: false, effect_id: 'solid', color: '#ffffff', brightness: 70, speed: 30 },
})
const form = reactive(FORM_DEFAULT())

// ─── Edu labels ────────────────────────────────────────────
const AGE_LABELS = { bambino: 'Bambino', ragazzo: 'Ragazzo', adulto: 'Adulto' }
const MODE_LABELS_EDU = {
  free_conversation: 'Conversazione Libera',
  teaching_general: 'Insegnamento Generale',
  interactive_story: 'Storia Interattiva',
  animal_sounds_games: 'Animali e Versi',
  quiz: 'Quiz',
  math: 'Matematica',
  foreign_languages: 'Lingue Straniere',
}
const LANG_LABELS = { english: 'Inglese', spanish: 'Spagnolo', german: 'Tedesco', french: 'Francese', japanese: 'Giapponese', chinese: 'Cinese' }

const eduSummary = computed(() => {
  const ec = form.edu_config
  const parts = [AGE_LABELS[ec.age_group] || ec.age_group, MODE_LABELS_EDU[ec.activity_mode] || ec.activity_mode]
  if (ec.activity_mode === 'foreign_languages') parts.push(LANG_LABELS[ec.language_target] || ec.language_target)
  parts.push(`Step ${ec.learning_step}`)
  return parts.join(' · ')
})

// ─── File browser ──────────────────────────────────────────
async function loadFiles(path = '') {
  loadingFiles.value = true
  try {
    const { data } = await guardedCall(() => getApi().get(`/files/list?path=${encodeURIComponent(path)}`))
    browserFiles.value = data.entries || []
    currentPath.value = data.current_path || defaultRoot.value
    if (!defaultRoot.value) defaultRoot.value = data.default_path || currentPath.value
  } catch (e) {
    console.error('Errore caricamento cartella', e)
  } finally {
    loadingFiles.value = false
  }
}

function goUp() {
  const parts = currentPath.value.split('/').filter(Boolean)
  if (parts.length > 1) {
    parts.pop()
    loadFiles('/' + parts.join('/'))
  }
}

function handleExplorerClick(item) {
  if (item.is_dir) {
    loadFiles(item.path)
  } else if (form.mode === 'media_folder') {
    form.folder = item.path
  }
}

function selectCurrentFolder() {
  form.folder = currentPath.value
}

function shortPath(p) {
  if (!p) return '/'
  const parts = p.split('/').filter(Boolean)
  if (parts.length <= 2) return p
  return '.../' + parts.slice(-2).join('/')
}

function onModeChange() {
  // Clear folder when switching away from media_folder
  if (form.mode !== 'media_folder') form.folder = ''
}

// ─── Profile CRUD ──────────────────────────────────────────
async function loadProfiles() {
  loading.value = true
  try {
    const { data } = await guardedCall(() => getApi().get('/rfid/profiles'))
    profiles.value = Array.isArray(data) ? data : []
  } catch (e) { console.error(extractApiError(e)) } finally { loading.value = false }
}

async function loadLedEffects() {
  try {
    const { data } = await guardedCall(() => getApi().get('/led/effects'))
    ledEffects.value = data?.effects || []
  } catch (e) {}
}

async function loadCurrentRfid() {
  try {
    const { data } = await guardedCall(() => getApi().get('/rfid/current'))
    currentRfid.value = data?.current_rfid ? data : null
  } catch (e) {}
}

async function saveProfile() {
  if (!form.rfid_code.trim() || !form.name.trim()) return
  isSaving.value = true; saveError.value = ''
  const payload = {
    ...form,
    rfid_code: form.rfid_code.trim().toUpperCase(),
    led: form.led.enabled ? { ...form.led } : undefined,
    edu_config: form.mode === 'edu_ai' ? { ...form.edu_config } : undefined,
  }
  try {
    if (isEditing.value) await guardedCall(() => getApi().put(`/rfid/profile/${payload.rfid_code}`, payload))
    else await guardedCall(() => getApi().post('/rfid/profile', payload))
    showSuccess(isEditing.value ? 'Profilo aggiornato.' : 'Profilo creato.')
    resetForm(); await loadProfiles()
  } catch (e) { saveError.value = extractApiError(e, 'Errore salvataggio') }
  finally { isSaving.value = false }
}

async function deleteProfile(code) {
  if (!confirm(`Eliminare il profilo "${code}"?`)) return
  clearFeedback()
  try {
    await guardedCall(() => getApi().delete(`/rfid/profile/${code}`))
    showSuccess(`Profilo "${code}" eliminato.`)
    await loadProfiles()
  } catch (e) {
    showError(extractApiError(e, 'Errore eliminazione profilo'))
  }
}

async function triggerProfile(code) {
  try {
    await guardedCall(() => getApi().post('/rfid/trigger', { rfid_code: code }))
    await loadCurrentRfid()
  } catch (e) {
    showError(extractApiError(e, 'Errore trigger profilo'))
  }
}

function editProfile(p) {
  isEditing.value = true
  Object.assign(form, FORM_DEFAULT())
  Object.assign(form, {
    ...p,
    led: p.led ? { ...p.led } : FORM_DEFAULT().led,
    edu_config: p.edu_config ? { ...EDU_CONFIG_DEFAULT(), ...p.edu_config } : EDU_CONFIG_DEFAULT(),
  })
}

function resetForm() {
  isEditing.value = false; isScanning.value = false
  saveError.value = ''
  Object.assign(form, FORM_DEFAULT())
}

function waitForScan() { isScanning.value = true; form.rfid_code = '' }

function handleRfidScanned(data) {
  if (isScanning.value && data?.uid) { form.rfid_code = data.uid; isScanning.value = false }
}

// ─── Display helpers ───────────────────────────────────────
function modeIcon(m) {
  return { media_folder: '🎵', web_media: '🌐', ai_chat: '🦉', edu_ai: '🎓', school: '🏫', entertainment: '🎮' }[m] || '🏷️'
}
function modeLabel(m) {
  return { media_folder: 'Cartella Media', web_media: 'Contenuto Web', ai_chat: 'AI Chat', edu_ai: 'AI Educativa', school: 'Scuola (wizard)', entertainment: 'Intrattenimento (wizard)' }[m] || m
}
function profileTarget(p) {
  if (p.mode === 'media_folder') return p.folder || ''
  if (p.mode === 'web_media') return p.web_media_url || ''
  if (p.mode === 'ai_chat') return (p.ai_prompt || 'Prompt AI').slice(0, 60)
  if (p.mode === 'edu_ai' && p.edu_config) {
    const ec = p.edu_config
    const parts = [AGE_LABELS[ec.age_group] || ec.age_group, MODE_LABELS_EDU[ec.activity_mode] || ec.activity_mode]
    if (ec.activity_mode === 'foreign_languages') parts.push(LANG_LABELS[ec.language_target] || ec.language_target)
    return parts.join(' · ')
  }
  if (p.mode === 'school') return 'Avvia wizard Scuola'
  if (p.mode === 'entertainment') return 'Avvia wizard Intrattenimento'
  return ''
}

// ─── Lifecycle ─────────────────────────────────────────────
onMounted(() => {
  loadProfiles(); loadLedEffects(); loadCurrentRfid(); loadFiles()
  const s = getSocket()
  if (s) {
    s.on('rfid_scanned', handleRfidScanned)
    s.on('public_snapshot', snap => {
      const mr = snap?.media_runtime
      currentRfid.value = mr?.current_rfid
        ? {
            current_rfid: mr.current_rfid,
            current_profile_name: mr.current_profile_name,
            current_mode: mr.current_mode,
            current_media_path: mr.current_media_path,
            web_content_type: mr.web_content_type,
          }
        : null
    })
  }
})
onBeforeUnmount(() => {
  const s = getSocket()
  if (s) { s.off('rfid_scanned', handleRfidScanned); s.off('public_snapshot') }
})
</script>

<style scoped>
.admin-media-statuine { display: flex; flex-direction: column; gap: 25px; }
.ms-header h2 { margin: 0; color: #fff; }
.ms-header p { color: #aaa; margin: 5px 0 0; }

/* Feedback banner */
.banner { padding: 12px 16px; border-radius: 10px; display: flex; justify-content: space-between; align-items: center; font-size: 0.95rem; gap: 10px; }
.banner-error   { background: #3b1212; color: #ef9a9a; border: 1px solid #c62828; }
.banner-success { background: #1b3a1b; color: #a5d6a7; border: 1px solid #388e3c; }
.banner-warning { background: #3b2e0a; color: #ffe082; border: 1px solid #f9a825; }
.banner-info    { background: #1a2a3b; color: #90caf9; border: 1px solid #1565c0; }
.banner-close { background: none; border: none; cursor: pointer; opacity: 0.7; color: inherit; font-size: 1rem; padding: 0 4px; }
.banner-close:hover { opacity: 1; }

/* Main layout */
.ms-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 900px) { .ms-layout { grid-template-columns: 1fr; } }

.card { background: #2a2a35; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,.2); }
.card h3 { margin-top: 0; border-bottom: 1px solid #3a3a48; padding-bottom: 10px; color: #ffd27b; }

/* Form panel */
.ms-form-panel { display: flex; flex-direction: column; gap: 0; }
.form-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px; }
@media (max-width: 700px) { .form-grid-2 { grid-template-columns: 1fr; } }
.form-group-full { grid-column: 1 / -1; }
.form-group-inline { display: flex; align-items: center; gap: 10px; }
.checkbox-lg { width: 20px; height: 20px; cursor: pointer; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: .9rem; color: #ccc; font-weight: bold; }
.form-group input[type="text"],
.form-group input[type="url"],
.form-group select,
.form-group textarea { background: #1e1e26; border: 1px solid #3a3a48; color: white; padding: 9px 12px; border-radius: 8px; font-size: .95rem; }
.form-group textarea { resize: vertical; }
.form-group input[type="range"] { width: 100%; }
.mode-section { background: #1e1e26; border: 1px solid #3a3a48; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
.mode-section h4 { margin: 0 0 12px; color: #ffd27b; }
.mode-hint { font-size: .85rem; color: #aaa; margin: -4px 0 12px; font-style: italic; }

/* Selected path display */
.selected-path-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.selected-path-display {
  flex: 1; background: #13131b; border: 1px solid #3a3a48; border-radius: 8px;
  padding: 9px 12px; font-size: .88rem; color: #777; font-family: monospace;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.selected-path-display.has-value { color: #4caf50; border-color: #4caf50; }
.btn-clear-path { background: transparent; border: 1px solid #555; color: #ff6b6b; border-radius: 6px; padding: 6px 10px; cursor: pointer; font-size: .85rem; }
.btn-clear-path:hover { background: #3b1212; }

.uid-input-group { display: flex; gap: 6px; }
.uid-input-group input { flex: 1; background: #1e1e26; border: 1px solid #3a3a48; color: white; padding: 9px 12px; border-radius: 8px; }
.btn-scan { background: #3f51b5; color: white; border: none; padding: 0 14px; border-radius: 8px; cursor: pointer; white-space: nowrap; font-size: .9rem; }
.btn-scan.scanning { background: #ff9800; animation: pulse 1s infinite alternate; }
@keyframes pulse { from { opacity: 1; } to { opacity: .7; } }
.scan-hint { margin: 4px 0 0; font-size: .85rem; color: #ff9800; font-style: italic; }

/* LED section */
.led-section { margin-bottom: 15px; border: 1px solid #3a3a48; border-radius: 8px; overflow: hidden; }
.led-toggle { display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; background: #1e1e26; cursor: pointer; user-select: none; }
.led-toggle:hover { background: #2a2a35; }
.toggle-indicator { font-size: .8rem; font-weight: bold; padding: 3px 10px; border-radius: 20px; background: #555; color: #aaa; }
.toggle-indicator.on { background: #4caf50; color: #fff; }
.led-config { padding: 15px; background: #1e1e26; }
.led-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
.led-row input[type="range"] { width: 100%; }
.led-row input[type="color"] { width: 100%; height: 38px; padding: 2px; border-radius: 6px; border: 1px solid #3a3a48; background: #1e1e26; cursor: pointer; }

.form-actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 10px; }
.btn-save { background: #4caf50; color: white; border: none; padding: 10px 22px; border-radius: 8px; font-weight: bold; cursor: pointer; }
.btn-save:disabled { background: #555; color: #888; cursor: not-allowed; }
.btn-cancel { background: transparent; color: #ccc; border: 1px solid #555; padding: 10px 20px; border-radius: 8px; cursor: pointer; }
.form-error { color: #ff6b6b; font-size: .9rem; margin: 6px 0 0; }

/* Wizard section */
.wizard-mode-section { border: 1px solid #3a5a8a; background: #1a2a3a; }
.wizard-mode-info p { color: #9ec8e4; font-size: .9rem; margin: 6px 0; }

/* Edu section */
.edu-ai-section .mode-hint { font-size: .85rem; color: #aaa; margin: -4px 0 12px; font-style: italic; }
.edu-summary { margin-top: 12px; }
.edu-tag { display: inline-block; background: #2e7d32; color: #fff; font-size: .82rem; padding: 4px 12px; border-radius: 20px; font-weight: bold; }

/* Explorer panel */
.ms-explorer-panel { display: flex; flex-direction: column; gap: 0; }
.explorer-header { margin-bottom: 10px; }
.explorer-nav-bar { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.btn-nav { background: #3a3a48; border: none; color: #ccc; border-radius: 6px; padding: 6px 10px; cursor: pointer; font-size: 1rem; }
.btn-nav:disabled { opacity: .4; cursor: not-allowed; }
.btn-nav:not(:disabled):hover { background: #4a4a58; }
.breadcrumb-path { flex: 1; font-size: .8rem; color: #888; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.select-folder-bar { margin-bottom: 12px; }
.btn-select-folder {
  width: 100%; background: #3f51b5; color: white; border: none;
  padding: 10px 16px; border-radius: 8px; font-weight: bold;
  cursor: pointer; font-size: .95rem; transition: background .2s;
}
.btn-select-folder:hover { background: #5c6bc0; }

.explorer-loading { text-align: center; color: #aaa; padding: 20px; font-style: italic; }

.explorer-list { list-style: none; padding: 0; margin: 0; max-height: 380px; overflow-y: auto; }
.explorer-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-bottom: 1px solid #3a3a48;
  cursor: pointer; transition: background .15s; border-radius: 6px;
}
.explorer-item:hover { background: #3a3a48; }
.explorer-item.is-selected { background: #1b3a1b; border-color: #4caf50; }
.ex-icon { font-size: 1.2rem; flex-shrink: 0; }
.ex-name { flex: 1; color: #ddd; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: .92rem; }
.ex-select-hint { font-size: .78rem; color: #888; flex-shrink: 0; }
.explorer-item.is-selected .ex-select-hint { color: #4caf50; }
.explorer-item.is-dir .ex-name { color: #fff; font-weight: 600; }
.explorer-empty { padding: 20px; text-align: center; color: #888; font-style: italic; }

/* Current RFID state */
.current-card { margin-top: 16px; padding: 12px; background: #1a2a1a; border: 1px solid #4caf50; border-radius: 8px; }
.current-card h4 { margin: 0 0 8px; color: #4caf50; font-size: .95rem; }
.current-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: .85rem; }
.current-grid .label { color: #aaa; margin-right: 4px; }

/* Profiles list */
.list-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }
.btn-refresh { background: transparent; border: 1px solid #555; color: #ccc; padding: 4px 10px; border-radius: 6px; cursor: pointer; }
.rfid-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; margin-top: 15px; }
.rfid-item { background: #1e1e26; border: 1px solid #3a3a48; border-radius: 10px; padding: 15px; display: flex; align-items: flex-start; gap: 12px; transition: transform .2s, border-color .2s; }
.rfid-item:hover { transform: translateY(-2px); border-color: #3f51b5; }
.rfid-item.active { border-color: #4caf50; }
.rfid-item.disabled { opacity: .6; }
.rfid-icon { font-size: 2rem; background: #2a2a35; min-width: 50px; height: 50px; display: flex; align-items: center; justify-content: center; border-radius: 10px; }
.rfid-info { flex: 1; overflow: hidden; }
.rfid-info h4 { margin: 0 0 4px; color: #fff; }
.uid-code { margin: 0 0 4px; font-size: .8rem; color: #888; font-family: monospace; }
.mode-badge { display: inline-block; font-size: .75rem; padding: 2px 8px; border-radius: 10px; background: #3f51b5; color: #fff; margin: 2px 0; }
.mode-badge.web_media { background: #006064; }
.mode-badge.ai_chat { background: #ff9800; }
.mode-badge.edu_ai { background: #2e7d32; }
.mode-badge.school { background: #1565c0; }
.mode-badge.entertainment { background: #6a1b9a; }
.target-path { margin: 4px 0 0; font-size: .8rem; color: #aaa; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.led-badge { margin: 4px 0 0; font-size: .8rem; color: #ffd27b; display: flex; align-items: center; gap: 5px; }
.color-dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; border: 1px solid #555; }
.disabled-badge { margin: 4px 0 0; font-size: .8rem; color: #ff6b6b; }
.rfid-actions { display: flex; flex-direction: column; gap: 5px; }
.btn-icon { background: #2a2a35; border: none; border-radius: 6px; padding: 8px; cursor: pointer; transition: background .2s; font-size: 1rem; }
.btn-icon:hover { background: #3a3a48; }
.btn-icon:disabled { opacity: .4; cursor: not-allowed; }
.btn-trigger { color: #4caf50; }
.text-red { color: #ff4d4d; }
.loading-state { text-align: center; padding: 20px; color: #aaa; }
.empty-state { text-align: center; padding: 30px; color: #aaa; font-style: italic; }
</style>
