<template>
  <div class="admin-rfid">

    <div class="rfid-header">
      <h2>Statuine Magiche (RFID) 🏷️</h2>
      <p>Gestisci i profili avanzati delle statuine: cartella media, webradio, AI, feed RSS.</p>
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- FORM PROFILO COMPLETO -->
    <div class="rfid-form-card">
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
          <select v-model="form.mode">
            <option value="media_folder">🎵 Cartella Media</option>
            <option value="webradio">📻 Webradio</option>
            <option value="ai_chat">🦉 Chat AI (Gufetto)</option>
            <option value="rss_feed">📰 Feed RSS</option>
            <option value="edu_ai">🎓 AI Educativa</option>
          </select>
        </div>
        <div class="form-group form-group-inline">
          <label>Abilitata</label>
          <input type="checkbox" v-model="form.enabled" class="checkbox-lg" />
        </div>
      </div>

      <!-- Campi dinamici per mode -->
      <div v-if="form.mode === 'media_folder'" class="mode-section">
        <h4>\ud83c\udfb5 Cartella Media</h4>
        <div class="form-grid-2">
          <div class="form-group form-group-full">
            <label>Percorso Cartella</label>
            <input type="text" v-model="form.folder" placeholder="/home/gufobox/media/storie" />
          </div>
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

      <div v-if="form.mode === 'webradio'" class="mode-section">
        <h4>\ud83d\udcfb Webradio</h4>
        <div class="form-grid-2">
          <div class="form-group form-group-full">
            <label>URL Stream</label>
            <input type="url" v-model="form.webradio_url" placeholder="http://..." />
          </div>
          <div class="form-group">
            <label>Volume {{ form.volume }}%</label>
            <input type="range" min="0" max="100" v-model.number="form.volume" />
          </div>
        </div>
      </div>

      <div v-if="form.mode === 'ai_chat'" class="mode-section">
        <h4>🦉 Chat AI (Gufetto)</h4>
        <div class="form-group form-group-full">
          <label>Prompt extra (opzionale)</label>
          <textarea v-model="form.ai_prompt" rows="3" placeholder="Es. Sei un pirata gentile..."></textarea>
        </div>
      </div>

      <!-- EDU AI section -->
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

      <div v-if="form.mode === 'rss_feed'" class="mode-section">
        <h4>\ud83d\udcf0 Feed RSS</h4>
        <div class="form-grid-2">
          <div class="form-group form-group-full">
            <label>URL Feed RSS</label>
            <div class="url-input-group">
              <input type="url" v-model="form.rss_url" placeholder="https://..." />
              <button class="btn-preview" @click="previewRss" :disabled="!form.rss_url || rssLoading">
                {{ rssLoading ? '\u23f3' : '\ud83d\udc41\ufe0f Preview' }}
              </button>
            </div>
          </div>
          <div class="form-group">
            <label>Limite articoli: {{ form.rss_limit }}</label>
            <input type="range" min="1" max="50" v-model.number="form.rss_limit" />
          </div>
        </div>
        <div v-if="rssPreviewItems.length" class="rss-preview">
          <h5>Preview Feed ({{ rssPreviewItems.length }} articoli)</h5>
          <div v-for="item in rssPreviewItems" :key="item.link" class="rss-item">
            <a :href="item.link" target="_blank" rel="noopener">{{ item.title }}</a>
            <p v-if="item.summary" class="rss-summary">{{ item.summary.slice(0, 150) }}</p>
            <span class="rss-date">{{ item.published }}</span>
          </div>
        </div>
        <p v-if="rssPreviewError" class="form-error">{{ rssPreviewError }}</p>
      </div>

      <!-- Immagine statuina -->
      <div class="form-group" style="margin-bottom:15px">
        <label>Immagine Statuina (percorso, opzionale)</label>
        <input type="text" v-model="form.image_path" placeholder="/home/gufobox/media/immagini/bella.png" />
      </div>

      <!-- Blocco LED -->
      <div class="led-section">
        <div class="led-toggle" @click="form.led.enabled = !form.led.enabled">
          <span>\ud83d\udca1 Effetto LED per questa statuina</span>
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
              <label>Luminosit\u00e0 {{ form.led.brightness }}%</label>
              <input type="range" min="0" max="100" v-model.number="form.led.brightness" />
            </div>
            <div class="form-group">
              <label>Velocit\u00e0 {{ form.led.speed }}%</label>
              <input type="range" min="0" max="100" v-model.number="form.led.speed" />
            </div>
          </div>
        </div>
      </div>

      <p v-if="saveError" class="form-error">{{ saveError }}</p>
      <div class="form-actions">
        <button v-if="isEditing" class="btn-cancel" @click="resetForm">Annulla</button>
        <button class="btn-save" @click="saveProfile" :disabled="!form.rfid_code.trim() || !form.name.trim() || isSaving">
          {{ isSaving ? '\u23f3 Salvataggio...' : '\ud83d\udcbe Salva Profilo' }}
        </button>
      </div>
    </div>

    <!-- STATO CORRENTE -->
    <div v-if="currentRfid" class="current-card">
      <h3>\u25b6\ufe0f In Riproduzione</h3>
      <div class="current-grid">
        <div><span class="label">RFID:</span> {{ currentRfid.current_rfid }}</div>
        <div><span class="label">Profilo:</span> {{ currentRfid.current_profile_name }}</div>
        <div><span class="label">Modalit\u00e0:</span> {{ currentRfid.current_mode }}</div>
        <div v-if="currentRfid.current_media_path"><span class="label">File:</span> {{ currentRfid.current_media_path }}</div>
        <div v-if="currentRfid.current_playlist?.length">
          <span class="label">Playlist:</span> {{ currentRfid.playlist_index + 1 }} / {{ currentRfid.current_playlist.length }}
        </div>
        <div v-if="currentRfid.rss_state?.items?.length"><span class="label">Articoli RSS:</span> {{ currentRfid.rss_state.items.length }}</div>
      </div>
    </div>

    <!-- LISTA PROFILI -->
    <div class="rfid-list-card">
      <div class="list-header">
        <h3>Profili Configurati</h3>
        <button class="btn-refresh" @click="loadProfiles">\ud83d\udd04</button>
      </div>
      <div v-if="loading" class="loading-state">Caricamento... ⏳</div>
      <div v-else-if="profiles.length === 0" class="empty-state">
        Nessun profilo configurato. Usa il form qui sopra per aggiungere la prima statuina.
      </div>
      <div v-else class="rfid-grid">
        <div v-for="p in profiles" :key="p.rfid_code" class="rfid-item"
             :class="{ active: currentRfid?.current_rfid === p.rfid_code, disabled: !p.enabled }">
          <div class="rfid-icon">{{ modeIcon(p.mode) }}</div>
          <div class="rfid-info">
            <h4>{{ p.name }}</h4>
            <p class="uid-code">{{ p.rfid_code }}</p>
            <p class="mode-badge" :class="p.mode">{{ modeLabel(p.mode) }}</p>
            <p class="target-path">{{ profileTarget(p) }}</p>
            <p v-if="p.led?.enabled" class="led-badge">\ud83d\udca1 {{ p.led.effect_id }} <span class="color-dot" :style="{ background: p.led.color }"></span></p>
            <p v-if="!p.enabled" class="disabled-badge">\u26d4 Disabilitata</p>
          </div>
          <div class="rfid-actions">
            <button class="btn-icon" @click="editProfile(p)" title="Modifica">\u270f\ufe0f</button>
            <button class="btn-icon btn-trigger" @click="triggerProfile(p.rfid_code)" title="Trigger" :disabled="!p.enabled">\u25b6\ufe0f</button>
            <button class="btn-icon text-red" @click="deleteProfile(p.rfid_code)" title="Elimina">\ud83d\uddd1\ufe0f</button>
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

const profiles = ref([])
const loading = ref(false)
const isSaving = ref(false)
const saveError = ref('')
const isEditing = ref(false)
const isScanning = ref(false)
const ledEffects = ref([])
const currentRfid = ref(null)
const rssPreviewItems = ref([])
const rssPreviewError = ref('')
const rssLoading = ref(false)

const EDU_CONFIG_DEFAULT = () => ({
  age_group: 'bambino',
  activity_mode: 'free_conversation',
  language_target: 'english',
  learning_step: 1,
})

const FORM_DEFAULT = () => ({
  rfid_code: '', name: '', enabled: true, mode: 'media_folder',
  image_path: '', folder: '', webradio_url: '', ai_prompt: '',
  rss_url: '', rss_limit: 10, volume: 70, loop: true,
  edu_config: EDU_CONFIG_DEFAULT(),
  led: { enabled: false, effect_id: 'solid', color: '#ffffff', brightness: 70, speed: 30 },
})
const form = reactive(FORM_DEFAULT())

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
const LANG_LABELS = { english: 'Inglese', spanish: 'Spagnolo', german: 'Tedesco', french: 'Francese' }

const eduSummary = computed(() => {
  const ec = form.edu_config
  const parts = [AGE_LABELS[ec.age_group] || ec.age_group, MODE_LABELS_EDU[ec.activity_mode] || ec.activity_mode]
  if (ec.activity_mode === 'foreign_languages') parts.push(LANG_LABELS[ec.language_target] || ec.language_target)
  parts.push(`Step ${ec.learning_step}`)
  return parts.join(' · ')
})

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

async function previewRss() {
  if (!form.rss_url) return
  rssLoading.value = true; rssPreviewError.value = ''; rssPreviewItems.value = []
  try {
    const { data } = await guardedCall(() => getApi().post('/rss/fetch', { rss_url: form.rss_url, limit: form.rss_limit }))
    rssPreviewItems.value = data?.items || []
    if (!rssPreviewItems.value.length) rssPreviewError.value = 'Nessun articolo trovato.'
  } catch (e) { rssPreviewError.value = extractApiError(e) }
  finally { rssLoading.value = false }
}

function editProfile(p) {
  isEditing.value = true
  Object.assign(form, FORM_DEFAULT())
  Object.assign(form, {
    ...p,
    led: p.led ? { ...p.led } : FORM_DEFAULT().led,
    edu_config: p.edu_config ? { ...EDU_CONFIG_DEFAULT(), ...p.edu_config } : EDU_CONFIG_DEFAULT(),
  })
  rssPreviewItems.value = []; rssPreviewError.value = ''
}

function resetForm() {
  isEditing.value = false; isScanning.value = false
  saveError.value = ''; rssPreviewItems.value = []; rssPreviewError.value = ''
  Object.assign(form, FORM_DEFAULT())
}

function waitForScan() { isScanning.value = true; form.rfid_code = '' }

function handleRfidScanned(data) { if (isScanning.value && data?.uid) { form.rfid_code = data.uid; isScanning.value = false } }

function modeIcon(m) { return { media_folder: '🎵', webradio: '📻', ai_chat: '🦉', rss_feed: '📰', edu_ai: '🎓' }[m] || '🏷️' }
function modeLabel(m) { return { media_folder: 'Cartella Media', webradio: 'Webradio', ai_chat: 'AI Chat', rss_feed: 'Feed RSS', edu_ai: 'AI Educativa' }[m] || m }
function profileTarget(p) {
  if (p.mode === 'media_folder') return p.folder || ''
  if (p.mode === 'webradio') return p.webradio_url || ''
  if (p.mode === 'ai_chat') return (p.ai_prompt || 'Prompt AI').slice(0, 60)
  if (p.mode === 'rss_feed') return p.rss_url || ''
  if (p.mode === 'edu_ai' && p.edu_config) {
    const ec = p.edu_config
    const parts = [AGE_LABELS[ec.age_group] || ec.age_group, MODE_LABELS_EDU[ec.activity_mode] || ec.activity_mode]
    if (ec.activity_mode === 'foreign_languages') parts.push(LANG_LABELS[ec.language_target] || ec.language_target)
    return parts.join(' · ')
  }
  return ''
}

onMounted(() => {
  loadProfiles(); loadLedEffects(); loadCurrentRfid()
  const s = getSocket()
  if (s) {
    s.on('rfid_scanned', handleRfidScanned)
    s.on('public_snapshot', snap => {
      const mr = snap?.media_runtime
      currentRfid.value = mr?.current_rfid ? { current_rfid: mr.current_rfid, current_profile_name: mr.current_profile_name, current_mode: mr.current_mode, current_media_path: mr.current_media_path, current_playlist: mr.current_playlist, playlist_index: mr.playlist_index, rss_state: mr.rss_state } : null
    })
  }
})
onBeforeUnmount(() => { const s = getSocket(); if (s) { s.off('rfid_scanned', handleRfidScanned); s.off('public_snapshot') } })
</script>

<style scoped>
.admin-rfid { display: flex; flex-direction: column; gap: 25px; }
.rfid-header h2 { margin: 0; color: #fff; }
.rfid-header p { color: #aaa; margin: 5px 0 0; }

/* Feedback banner */
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
.banner-info    { background: #1a2a3b; color: #90caf9; border: 1px solid #1565c0; }
.banner-close { background: none; border: none; cursor: pointer; opacity: 0.7; color: inherit; font-size: 1rem; padding: 0 4px; }
.banner-close:hover { opacity: 1; }

.scan-hint { margin: 4px 0 0; font-size: 0.85rem; color: #ff9800; font-style: italic; }

.rfid-form-card, .rfid-list-card, .current-card { background: #2a2a35; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,.2); }
.rfid-form-card h3, .rfid-list-card h3, .current-card h3 { margin-top: 0; border-bottom: 1px solid #3a3a48; padding-bottom: 10px; color: #ffd27b; }
.form-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px; }
@media (max-width: 700px) { .form-grid-2 { grid-template-columns: 1fr; } }
.form-group-full { grid-column: 1 / -1; }
.form-group-inline { display: flex; align-items: center; gap: 10px; }
.checkbox-lg { width: 20px; height: 20px; cursor: pointer; }
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group label { font-size: .9rem; color: #ccc; font-weight: bold; }
.form-group input[type="text"], .form-group input[type="url"], .form-group select, .form-group textarea { background: #1e1e26; border: 1px solid #3a3a48; color: white; padding: 9px 12px; border-radius: 8px; font-size: .95rem; }
.form-group textarea { resize: vertical; }
.form-group input[type="range"] { width: 100%; }
.mode-section { background: #1e1e26; border: 1px solid #3a3a48; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
.mode-section h4 { margin: 0 0 12px; color: #ffd27b; }
.uid-input-group, .url-input-group { display: flex; gap: 6px; }
.uid-input-group input, .url-input-group input { flex: 1; background: #1e1e26; border: 1px solid #3a3a48; color: white; padding: 9px 12px; border-radius: 8px; }
.btn-scan, .btn-preview { background: #3f51b5; color: white; border: none; padding: 0 14px; border-radius: 8px; cursor: pointer; white-space: nowrap; font-size: .9rem; }
.btn-scan.scanning { background: #ff9800; animation: pulse 1s infinite alternate; }
.btn-preview:disabled { background: #555; cursor: not-allowed; }
@keyframes pulse { from { opacity: 1; } to { opacity: .7; } }
.rss-preview { margin-top: 12px; background: #13131b; border-radius: 8px; padding: 12px; max-height: 300px; overflow-y: auto; }
.rss-preview h5 { margin: 0 0 10px; color: #ffd27b; font-size: .9rem; }
.rss-item { padding: 8px 0; border-bottom: 1px solid #2a2a35; }
.rss-item:last-child { border-bottom: none; }
.rss-item a { color: #7cb9ff; font-size: .9rem; text-decoration: none; }
.rss-summary { margin: 4px 0 0; font-size: .8rem; color: #aaa; }
.rss-date { font-size: .75rem; color: #666; }
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
.current-card { border: 1px solid #4caf50; }
.current-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; font-size: .9rem; }
.current-grid .label { color: #aaa; margin-right: 4px; }
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
.mode-badge.webradio { background: #9c27b0; }
.mode-badge.ai_chat { background: #ff9800; }
.mode-badge.rss_feed { background: #009688; }
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
.mode-badge.edu_ai { background: #2e7d32; }
.edu-ai-section .mode-hint { font-size: .85rem; color: #aaa; margin: -4px 0 12px; font-style: italic; }
.edu-summary { margin-top: 12px; }
.edu-tag { display: inline-block; background: #2e7d32; color: #fff; font-size: .82rem; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
.empty-state { text-align: center; padding: 30px; color: #aaa; font-style: italic; }
.loading-state { text-align: center; padding: 20px; color: #aaa; }
</style>
