<template>
  <div class="admin-file-manager">

    <!-- ── Toolbar principale ── -->
    <div class="toolbar">
      <div class="breadcrumbs">
        <button class="btn-icon" @click="goFileHome" title="Home">🏠</button>
        <button class="btn-icon" @click="goFileBack" :disabled="!canGoBack" title="Indietro">◀</button>
        <button class="btn-icon" @click="goFileForward" :disabled="!canGoForward" title="Avanti">▶</button>
        <button class="btn-icon" @click="goFileUp" title="Su">⬆️</button>
        <span class="bc-separator">/</span>
        <span
          v-for="(crumb, i) in breadcrumbs"
          :key="crumb.path"
          class="bc-segment"
        >
          <button class="bc-btn" @click="loadFileList(crumb.path)">{{ crumb.label }}</button>
          <span v-if="i < breadcrumbs.length - 1" class="bc-sep">/</span>
        </span>
      </div>

      <div class="actions">
        <button class="btn-action" @click="showNewFolderInput = !showNewFolderInput">📁 Nuova Cartella</button>
        <label class="btn-action btn-upload" title="Carica file (multipli supportati)">
          📤 Carica File
          <input
            type="file"
            multiple
            ref="fileInputRef"
            style="display: none"
            @change="(e) => uploadFiles(e, onUploadDone)"
          />
        </label>
      </div>
    </div>

    <!-- ── Nuova cartella inline ── -->
    <div v-if="showNewFolderInput" class="new-folder-row">
      <input
        v-model="newFolderName"
        class="input-inline"
        placeholder="Nome cartella..."
        @keydown.enter="doCreateFolder"
        @keydown.escape="showNewFolderInput = false"
        ref="newFolderInputRef"
        autofocus
      />
      <button class="btn-action" @click="doCreateFolder">Crea</button>
      <button class="btn-icon" @click="showNewFolderInput = false">✖</button>
    </div>

    <!-- ── Barra ricerca + sort ── -->
    <div class="search-sort-bar">
      <input
        v-model="fileSearch"
        class="input-search"
        placeholder="🔍 Cerca nella cartella..."
      />
      <select v-model="fileSortBy" class="sel-sort">
        <option value="name">Nome</option>
        <option value="size">Dimensione</option>
        <option value="mtime">Data modifica</option>
        <option value="type">Tipo</option>
      </select>
      <button class="btn-icon" @click="fileSortOrder = fileSortOrder === 'asc' ? 'desc' : 'asc'" :title="fileSortOrder === 'asc' ? 'Ordinamento crescente' : 'Ordinamento decrescente'">
        {{ fileSortOrder === 'asc' ? '⬆' : '⬇' }}
      </button>
      <select v-model="fileFilterType" class="sel-sort">
        <option value="">Tutti i tipi</option>
        <option value="dir">Cartelle</option>
        <option value="audio">Audio</option>
        <option value="video">Video</option>
        <option value="image">Immagini</option>
        <option value="archive">Archivi</option>
        <option value="text">Testo</option>
      </select>
    </div>

    <!-- ── Upload progress queue ── -->
    <div v-if="uploadQueue.length > 0" class="upload-queue">
      <div
        v-for="(item, i) in uploadQueue"
        :key="i"
        class="upload-item"
        :class="{ 'upload-error': item.status === 'error' }"
      >
        <span class="upload-name">{{ item.name }}</span>
        <div class="upload-progress-bar">
          <div class="upload-fill" :style="{ width: item.progress + '%' }"></div>
        </div>
        <span class="upload-pct">{{ item.status === 'error' ? '⚠️ ' + item.error : (item.status === 'done' ? '✔' : item.progress + '%') }}</span>
      </div>
    </div>

    <!-- ── Toolbar selezione / clipboard ── -->
    <div v-if="selectedCount > 0 || clipboardPaths.length > 0" class="selection-toolbar">
      <span v-if="selectedCount > 0">{{ selectedCount }} selezionati</span>
      <span v-if="clipboardPaths.length > 0" class="clipboard-hint">
        📋 {{ clipboardPaths.length }} in appunti ({{ clipboardMode === 'copy' ? 'copia' : 'taglia' }})
      </span>

      <div class="selection-actions">
        <button v-if="selectedCount > 0" class="btn-sm" @click="copySelected">📋 Copia</button>
        <button v-if="selectedCount > 0" class="btn-sm" @click="moveSelected">✂️ Taglia</button>
        <button v-if="clipboardPaths.length > 0" class="btn-sm btn-paste" @click="() => pasteClipboard(onJobDone)">📥 Incolla Qui</button>
        <button v-if="clipboardPaths.length > 0" class="btn-sm" @click="clearClipboard">✖ Svuota appunti</button>
        <button v-if="selectedCount > 0" class="btn-sm" @click="doCompress">🗜️ Comprimi</button>
        <button v-if="selectedCount > 0" class="btn-sm btn-danger" @click="doDelete">🗑 Elimina</button>
        <button v-if="selectedCount > 0" class="btn-sm" @click="clearSelection">Deseleziona tutto</button>
      </div>
    </div>

    <!-- ── Toast / feedback ── -->
    <transition name="toast-fade">
      <div v-if="toastMsg" class="toast" :class="'toast-' + toastType">{{ toastMsg }}</div>
    </transition>

    <!-- ── Errore cartella ── -->
    <div v-if="fileError" class="error-banner">⚠️ {{ fileError }}</div>

    <!-- ── Lista file ── -->
    <div class="file-list" @dragover.prevent @drop.prevent="onDrop">
      <!-- Loading -->
      <div v-if="fileLoading" class="empty-folder">
        <span class="spinner">⏳</span> Caricamento...
      </div>

      <!-- Empty state -->
      <div v-else-if="filteredEntries.length === 0 && !fileLoading" class="empty-folder">
        <div v-if="fileSearch || fileFilterType">
          🔍 Nessun risultato per i filtri applicati.
          <button class="btn-link" @click="fileSearch = ''; fileFilterType = ''">Rimuovi filtri</button>
        </div>
        <div v-else>
          📭 La cartella è vuota.
        </div>
      </div>

      <!-- Header colonne -->
      <div v-else class="file-list-header">
        <div></div>
        <div>Nome</div>
        <div class="col-type">Tipo</div>
        <div class="col-size">Dimensione</div>
        <div class="col-date">Modificato</div>
        <div class="col-actions"></div>
      </div>

      <div
        v-for="entry in filteredEntries"
        :key="entry.path"
        class="file-item"
        :class="{ 'selected': selectedFilePaths.includes(entry.path) }"
        @click.exact="openEntry(entry)"
        @click.ctrl.exact.prevent="toggleFileSelection(entry.path)"
        @click.meta.exact.prevent="toggleFileSelection(entry.path)"
        @click.shift.exact.prevent="toggleFileSelection(entry.path)"
      >
        <input
          type="checkbox"
          :checked="selectedFilePaths.includes(entry.path)"
          @click.stop
          @change="toggleFileSelection(entry.path)"
        />

        <div class="entry-info">
          <span class="icon">{{ fileIcon(entry) }}</span>
          <span class="name" :title="entry.name">{{ entry.name }}</span>
        </div>

        <div class="col-type entry-type">{{ entry.type }}</div>

        <div class="col-size entry-size">
          {{ entry.is_dir ? '—' : formatBytes(entry.size) }}
        </div>

        <div class="col-date entry-date">{{ formatDate(entry.mtime) }}</div>

        <div class="col-actions entry-menu">
          <button class="btn-icon" @click.stop="doRename(entry)" title="Rinomina">✏️</button>
          <button v-if="entry.type === 'archive'" class="btn-icon" @click.stop="doUncompress(entry)" title="Decomprimi">📦</button>
          <button class="btn-icon" @click.stop="doShowDetails(entry)" title="Dettagli">ℹ️</button>
        </div>
      </div>
    </div>

    <!-- ── Jobs panel ── -->
    <div v-if="activeJobs.length > 0" class="jobs-panel">
      <div class="jobs-header">⚙️ Operazioni in corso</div>
      <div v-for="job in activeJobs" :key="job.job_id" class="job-item">
        <div class="job-top">
          <span class="job-desc">{{ job.description }}</span>
          <span class="job-status" :class="'job-' + job.status">{{ job.status }}</span>
        </div>
        <div class="job-progress-bar">
          <div class="job-fill" :style="{ width: (job.progress_percent || 0) + '%' }"></div>
        </div>
        <div v-if="job.message || job.current_item" class="job-msg">{{ job.message || job.current_item }}</div>
        <div v-if="job.error" class="job-error">⚠️ {{ job.error }}</div>
      </div>
    </div>

    <!-- ── Modal dettagli ── -->
    <div v-if="detailsEntry" class="modal-overlay" @click.self="detailsEntry = null">
      <div class="modal-box">
        <div class="modal-header">
          <h3>{{ detailsEntry.name }}</h3>
          <button class="btn-icon" @click="detailsEntry = null">✖</button>
        </div>
        <div class="modal-body">
          <div class="detail-row"><span>Tipo</span><span>{{ detailsEntry.type }}</span></div>
          <div class="detail-row" v-if="!detailsEntry.is_dir"><span>Dimensione</span><span>{{ formatBytes(detailsEntry.size) }}</span></div>
          <div class="detail-row" v-if="detailsEntry.mime"><span>MIME</span><span>{{ detailsEntry.mime }}</span></div>
          <div class="detail-row"><span>Modificato</span><span>{{ formatDate(detailsEntry.mtime) }}</span></div>
          <div class="detail-row" v-if="detailsEntry.children_count != null"><span>Elementi</span><span>{{ detailsEntry.children_count }}</span></div>
          <div class="detail-row"><span>Leggibile</span><span>{{ detailsEntry.readable ? '✔' : '✖' }}</span></div>
          <div class="detail-row"><span>Scrivibile</span><span>{{ detailsEntry.writable ? '✔' : '✖' }}</span></div>
          <div class="detail-row path-row"><span>Path</span><span class="mono">{{ detailsEntry.path }}</span></div>
        </div>
      </div>
    </div>

    <!-- ── Rename modal ── -->
    <div v-if="renameEntry" class="modal-overlay" @click.self="renameEntry = null">
      <div class="modal-box modal-sm">
        <div class="modal-header">
          <h3>Rinomina</h3>
          <button class="btn-icon" @click="renameEntry = null">✖</button>
        </div>
        <div class="modal-body">
          <input
            v-model="renameNewName"
            class="input-inline"
            placeholder="Nuovo nome..."
            @keydown.enter="doRenameConfirm"
            @keydown.escape="renameEntry = null"
          />
        </div>
        <div class="modal-footer">
          <button class="btn-action" @click="doRenameConfirm">Rinomina</button>
          <button class="btn-sm" @click="renameEntry = null">Annulla</button>
        </div>
      </div>
    </div>

    <!-- ── Compress modal ── -->
    <div v-if="showCompressModal" class="modal-overlay" @click.self="showCompressModal = false">
      <div class="modal-box modal-sm">
        <div class="modal-header">
          <h3>Comprimi selezione</h3>
          <button class="btn-icon" @click="showCompressModal = false">✖</button>
        </div>
        <div class="modal-body">
          <input
            v-model="compressName"
            class="input-inline"
            placeholder="Nome archivio (senza .zip)..."
            @keydown.enter="doCompressConfirm"
            @keydown.escape="showCompressModal = false"
          />
        </div>
        <div class="modal-footer">
          <button class="btn-action" @click="doCompressConfirm">Comprimi</button>
          <button class="btn-sm" @click="showCompressModal = false">Annulla</button>
        </div>
      </div>
    </div>

    <!-- ── Preview Modal ── -->
    <div v-if="previewOpen" class="modal-overlay" @click.self="closePreview">
      <div class="modal-box modal-preview">
        <div class="modal-header">
          <h3>{{ previewFile?.name }}</h3>
          <button class="btn-icon" @click="closePreview">✖</button>
        </div>
        <div class="preview-body">
          <div v-if="previewLoading" class="loading">Caricamento ⏳</div>
          <template v-else-if="previewUrl">
            <img v-if="previewFile?.type === 'image'" :src="previewUrl" class="preview-media" />
            <audio v-else-if="previewFile?.type === 'audio'" :src="previewUrl" controls autoplay class="preview-media"></audio>
            <video v-else-if="previewFile?.type === 'video'" :src="previewUrl" controls autoplay class="preview-media"></video>
            <div v-else>Anteprima non supportata.</div>
          </template>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { useFileManager, formatBytes, formatDate, fileIcon } from '../../composables/useFileManager'
import { useApi } from '../../composables/useApi'

const {
  fileCurrentPath, fileLoading, fileError,
  selectedFilePaths, newFolderName,
  clipboardMode, clipboardPaths, selectedCount,
  previewOpen, previewFile, previewUrl, previewLoading,
  fileSearch, fileSortBy, fileSortOrder, fileFilterType,
  uploadQueue, filteredEntries,
  loadFileList, loadFileRoots, goFileHome, goFileUp, goFileBack, goFileForward,
  breadcrumbs, canGoBack, canGoForward,
  toggleFileSelection, selectAll, clearSelection, openEntry, closePreview,
  createFolder, renameEntry: doRenameEntry, moveSelected, copySelected,
  clearClipboard, pasteClipboard, deleteSelected, compressSelected,
  uncompressEntry, uploadFiles, fetchDetails,
  isPreviewable,
} = useFileManager()

const { guardedCall, getApi } = useApi()

// ── UI state ──
const showNewFolderInput = ref(false)
const newFolderInputRef = ref(null)
const fileInputRef = ref(null)

const toastMsg = ref('')
const toastType = ref('info')
let toastTimer = null

function showToast(msg, type = 'info', duration = 3000) {
  toastMsg.value = msg
  toastType.value = type
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastMsg.value = '' }, duration)
}

// ── Rename state ──
const renameEntry = ref(null)
const renameNewName = ref('')

// ── Compress state ──
const showCompressModal = ref(false)
const compressName = ref('archivio')

// ── Details modal ──
const detailsEntry = ref(null)

// ── Jobs panel ──
const allJobs = ref([])
const activeJobs = computed(() =>
  allJobs.value.filter(j => j.status === 'pending' || j.status === 'running')
)
let jobPollTimer = null

async function pollJobs() {
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/jobs'))
    allJobs.value = (data?.jobs || []).filter(j =>
      ['file_copy', 'file_move', 'file_compress', 'file_uncompress'].includes(j.type)
    )
  } catch (_) {}
}

// ── Actions ──
async function doCreateFolder() {
  await createFolder((msg) => {
    showNewFolderInput.value = false
    showToast(msg || 'Cartella creata', 'success')
  })
  if (fileError.value) showToast(fileError.value, 'error')
}

function doRename(entry) {
  renameEntry.value = entry
  renameNewName.value = entry.name
}

async function doRenameConfirm() {
  if (!renameEntry.value || !renameNewName.value) return
  await doRenameEntry(renameEntry.value, renameNewName.value)
  if (fileError.value) {
    showToast(fileError.value, 'error')
  } else {
    showToast('Rinominato', 'success')
  }
  renameEntry.value = null
}

async function doDelete() {
  if (!selectedCount.value) return
  const n = selectedCount.value
  if (!window.confirm(`Eliminare ${n} elemento/i? L'operazione non è reversibile.`)) return
  await deleteSelected((result) => {
    const deleted = result?.deleted ?? 0
    const errors = result?.errors ?? []
    if (errors.length) {
      showToast(`Eliminati ${deleted}/${n}, ${errors.length} errori`, 'warning')
    } else {
      showToast(`Eliminati ${deleted} elementi`, 'success')
    }
  })
  if (fileError.value) showToast(fileError.value, 'error')
}

function doCompress() {
  if (!selectedCount.value) return
  compressName.value = 'archivio'
  showCompressModal.value = true
}

async function doCompressConfirm() {
  showCompressModal.value = false
  await compressSelected(compressName.value, (job) => {
    showToast(`Compressione avviata (job ${job.job_id?.slice(0, 8)})`, 'info')
    pollJobs()
  })
  if (fileError.value) showToast(fileError.value, 'error')
}

async function doUncompress(entry) {
  await uncompressEntry(entry, (job) => {
    showToast(`Decompressione avviata (job ${job.job_id?.slice(0, 8)})`, 'info')
    pollJobs()
  })
  if (fileError.value) showToast(fileError.value, 'error')
}

async function doShowDetails(entry) {
  const d = await fetchDetails(entry.path)
  if (d) detailsEntry.value = d
  else if (fileError.value) showToast(fileError.value, 'error')
}

async function onJobDone(job) {
  showToast(`Operazione completata`, 'success')
  await pollJobs()
  await loadFileList(fileCurrentPath.value, { addToHistory: false })
}

async function onUploadDone({ filename }) {
  showToast(`"${filename}" caricato`, 'success')
}

// ── Drag & drop upload ──
function onDrop(ev) {
  const dt = ev.dataTransfer
  if (!dt?.files?.length) return
  const fakeEv = { target: { files: dt.files, value: '' } }
  uploadFiles(fakeEv, onUploadDone)
}

onMounted(async () => {
  await loadFileRoots()
  await loadFileList()
  await pollJobs()
  jobPollTimer = setInterval(pollJobs, 5000)
})

onUnmounted(() => {
  clearInterval(jobPollTimer)
  clearTimeout(toastTimer)
})
</script>

<style scoped>
.admin-file-manager {
  display: flex;
  flex-direction: column;
  gap: 10px;
  position: relative;
}

/* ── Toolbar ── */
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #2a2a35;
  padding: 10px 15px;
  border-radius: 8px;
  flex-wrap: wrap;
  gap: 10px;
}

.breadcrumbs {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.bc-segment { display: flex; align-items: center; gap: 2px; }
.bc-btn {
  background: none;
  border: none;
  color: #ffd27b;
  cursor: pointer;
  font-size: 0.9rem;
  padding: 2px 4px;
  border-radius: 3px;
}
.bc-btn:hover { background: #3a3a48; }
.bc-sep, .bc-separator { color: #aaa; margin: 0 2px; }

.actions { display: flex; gap: 10px; flex-wrap: wrap; }

.btn-action, .selection-actions button {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 7px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: bold;
  font-size: 0.85rem;
}
.btn-action.btn-upload { background: #4caf50; cursor: pointer; }
.btn-upload label { cursor: pointer; }

.btn-icon {
  background: transparent;
  border: none;
  font-size: 1.1rem;
  cursor: pointer;
  color: #fff;
  padding: 2px 4px;
  border-radius: 3px;
}
.btn-icon:hover { background: #3a3a48; }
.btn-icon:disabled { opacity: 0.4; cursor: default; }

.btn-sm {
  background: #444;
  color: #fff;
  border: none;
  padding: 5px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.82rem;
}
.btn-sm:hover { background: #555; }
.btn-sm.btn-paste { background: #f57c00; }
.btn-sm.btn-danger { background: #c62828; }

.btn-link {
  background: none;
  border: none;
  color: #ffd27b;
  cursor: pointer;
  text-decoration: underline;
  font-size: 0.9rem;
}

/* ── New folder row ── */
.new-folder-row {
  display: flex;
  gap: 8px;
  align-items: center;
  background: #2a2a35;
  padding: 8px 15px;
  border-radius: 8px;
}

.input-inline {
  flex: 1;
  background: #1e1e26;
  color: #fff;
  border: 1px solid #555;
  padding: 6px 10px;
  border-radius: 5px;
  font-size: 0.9rem;
}
.input-inline:focus { outline: none; border-color: #3f51b5; }

/* ── Search/sort bar ── */
.search-sort-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  background: #23232e;
  padding: 8px 12px;
  border-radius: 8px;
  flex-wrap: wrap;
}

.input-search {
  flex: 1;
  min-width: 160px;
  background: #1e1e26;
  color: #fff;
  border: 1px solid #444;
  padding: 6px 10px;
  border-radius: 5px;
  font-size: 0.88rem;
}
.input-search:focus { outline: none; border-color: #3f51b5; }

.sel-sort {
  background: #1e1e26;
  color: #fff;
  border: 1px solid #444;
  padding: 5px 8px;
  border-radius: 5px;
  font-size: 0.85rem;
  cursor: pointer;
}

/* ── Upload queue ── */
.upload-queue {
  background: #23232e;
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.upload-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.85rem;
}
.upload-item.upload-error .upload-pct { color: #ff6b6b; }
.upload-name { min-width: 120px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.upload-progress-bar { flex: 1; height: 6px; background: #3a3a48; border-radius: 3px; overflow: hidden; }
.upload-fill { height: 100%; background: #4caf50; transition: width 0.3s; }
.upload-pct { min-width: 50px; text-align: right; color: #aaa; font-size: 0.8rem; }

/* ── Selection toolbar ── */
.selection-toolbar {
  display: flex;
  align-items: center;
  background: #2d3250;
  padding: 8px 15px;
  border-radius: 8px;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 0.88rem;
}

.clipboard-hint { color: #ffd27b; font-style: italic; }
.selection-actions { display: flex; gap: 6px; flex-wrap: wrap; }

/* ── Toast ── */
.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: #333;
  color: #fff;
  padding: 10px 18px;
  border-radius: 8px;
  font-size: 0.9rem;
  z-index: 2000;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  max-width: 350px;
}
.toast-success { background: #2e7d32; }
.toast-error   { background: #c62828; }
.toast-warning { background: #e65100; }
.toast-fade-enter-active, .toast-fade-leave-active { transition: opacity 0.3s; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; }

/* ── Error banner ── */
.error-banner {
  background: #5c1a1a;
  color: #ffcdd2;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.88rem;
}

/* ── File list ── */
.file-list {
  background: #2a2a35;
  border-radius: 8px;
  overflow: hidden;
}

.file-list-header {
  display: grid;
  grid-template-columns: 40px 1fr 80px 90px 140px 100px;
  padding: 6px 15px;
  color: #aaa;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid #3a3a48;
}

.file-item {
  display: grid;
  grid-template-columns: 40px 1fr 80px 90px 140px 100px;
  align-items: center;
  padding: 9px 15px;
  border-bottom: 1px solid #3a3a48;
  cursor: pointer;
  transition: background 0.15s;
  user-select: none;
}
.file-item:hover { background: #33334a; }
.file-item.selected { background: #3a3a5c; }
.file-item:last-child { border-bottom: none; }

.entry-info { display: flex; align-items: center; gap: 8px; overflow: hidden; min-width: 0; }
.icon { font-size: 1.3rem; flex-shrink: 0; }
.name { flex: 1; min-width: 0; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.col-type, .entry-type { color: #aaa; font-size: 0.8rem; }
.col-size, .entry-size { color: #aaa; font-size: 0.82rem; text-align: right; padding-right: 10px; }
.col-date, .entry-date { color: #888; font-size: 0.78rem; }
.col-actions, .entry-menu { display: flex; gap: 4px; justify-content: flex-end; }

.empty-folder {
  padding: 40px 20px;
  text-align: center;
  color: #aaa;
  font-size: 0.95rem;
}
.spinner { font-size: 1.4rem; }

/* ── Jobs panel ── */
.jobs-panel {
  background: #1e2636;
  border: 1px solid #3a4a6a;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.jobs-header {
  font-weight: bold;
  font-size: 0.9rem;
  color: #90caf9;
}

.job-item {
  background: #23304a;
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.job-top { display: flex; justify-content: space-between; align-items: center; }
.job-desc { font-size: 0.85rem; color: #ddd; }
.job-status { font-size: 0.75rem; padding: 2px 7px; border-radius: 10px; font-weight: bold; }
.job-pending  { background: #555; color: #ddd; }
.job-running  { background: #1565c0; color: #fff; }
.job-done     { background: #2e7d32; color: #fff; }
.job-error    { background: #c62828; color: #fff; }

.job-progress-bar { height: 4px; background: #3a3a4a; border-radius: 2px; overflow: hidden; }
.job-fill { height: 100%; background: #42a5f5; transition: width 0.4s; }
.job-msg  { font-size: 0.78rem; color: #aaa; }
.job-error { font-size: 0.78rem; color: #ef9a9a; }

/* ── Modali ── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1500;
}

.modal-box {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  width: min(90vw, 520px);
  max-height: 85vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal-box.modal-sm { width: min(90vw, 360px); }
.modal-box.modal-preview { width: min(90vw, 800px); }

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.modal-header h3 { margin: 0; font-size: 1rem; }

.modal-body { display: flex; flex-direction: column; gap: 8px; }
.modal-footer { display: flex; gap: 8px; justify-content: flex-end; }

.detail-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.88rem;
  padding: 4px 0;
  border-bottom: 1px solid #3a3a48;
  gap: 10px;
}
.detail-row span:first-child { color: #aaa; min-width: 100px; }
.detail-row.path-row span:last-child { word-break: break-all; }
.mono { font-family: monospace; font-size: 0.82rem; }

.preview-body { display: flex; justify-content: center; }
.preview-media { max-width: 100%; max-height: 65vh; border-radius: 8px; }
.loading { padding: 20px; color: #aaa; }
</style>
