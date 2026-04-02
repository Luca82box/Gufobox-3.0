import { ref, computed } from 'vue'
import { useApi } from './useApi'

const UPLOAD_DONE_CLEAR_MS = 4000  // ms to keep completed upload entries visible

// Stato condiviso
const fileCurrentPath = ref('/home/gufobox/media')
const fileDefaultPath = ref('/home/gufobox/media')
const fileAllowedRoots = ref([])
const fileEntries = ref([])
const fileLoading = ref(false)
const fileError = ref('')
const selectedFilePaths = ref([])
const newFolderName = ref('')

const clipboardMode = ref('')
const clipboardPaths = ref([])

const fileHistory = ref([])
const fileHistoryIndex = ref(-1)

// Search / sort / filter (client-side)
const fileSearch = ref('')
const fileSortBy = ref('name')    // name | size | mtime | type
const fileSortOrder = ref('asc')  // asc | desc
const fileFilterType = ref('')    // '' | audio | video | image | dir | archive | text

// Upload progress
const uploadQueue = ref([])  // [{name, progress, status, error}]

// Stato Menu e Preview
const fileMenuOpen = ref(false)
const fileMenuTarget = ref(null)
const previewOpen = ref(false)
const previewFile = ref(null)
const previewUrl = ref('')
const previewLoading = ref(false)
let previewObjectUrl = null

// =========================================================
// Helper: formattazione
// =========================================================
export function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export function formatDate(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString()
}

export function fileIcon(entry) {
  if (entry?.is_dir) return '📁'
  const t = entry?.type || 'unknown'
  if (t === 'audio') return '🎵'
  if (t === 'video') return '🎬'
  if (t === 'image') return '🖼️'
  if (t === 'archive') return '🗜️'
  if (t === 'text') return '📝'
  return '📄'
}

export function useFileManager() {
  const { apiReady, guardedCall, getApi, extractApiError } = useApi()

  // 1. Variabili Calcolate (Computed)
  const selectedCount = computed(() => selectedFilePaths.value.length)
  const canGoBack = computed(() => fileHistoryIndex.value > 0)
  const canGoForward = computed(() => fileHistoryIndex.value >= 0 && fileHistoryIndex.value < fileHistory.value.length - 1)

  const fileParentPath = computed(() => {
    if (!fileCurrentPath.value) return fileDefaultPath.value
    const parts = fileCurrentPath.value.split('/').filter(Boolean)
    if (parts.length <= 1) return fileCurrentPath.value
    const parent = '/' + parts.slice(0, -1).join('/')
    const allowed = fileAllowedRoots.value.some(root => parent === root || parent.startsWith(root + '/'))
    return allowed ? parent : fileCurrentPath.value
  })

  const breadcrumbs = computed(() => {
    if (!fileCurrentPath.value) return []
    const parts = fileCurrentPath.value.split('/').filter(Boolean)
    const out = []
    let acc = ''
    for (const p of parts) {
      acc += '/' + p
      out.push({ label: p, path: acc })
    }
    return out
  })

  // Client-side filtered + sorted entries
  const filteredEntries = computed(() => {
    let entries = fileEntries.value
    const q = fileSearch.value.trim().toLowerCase()
    if (q) {
      entries = entries.filter(e => e.name.toLowerCase().includes(q))
    }
    if (fileFilterType.value) {
      if (fileFilterType.value === 'dir') {
        entries = entries.filter(e => e.is_dir)
      } else {
        entries = entries.filter(e => e.type === fileFilterType.value)
      }
    }
    const by = fileSortBy.value
    const rev = fileSortOrder.value === 'desc'
    const key = {
      name:  e => e.name.toLowerCase(),
      size:  e => e.size || 0,
      mtime: e => e.mtime || 0,
      type:  e => e.type || '',
    }[by] || (e => e.name.toLowerCase())
    const dirs = [...entries.filter(e => e.is_dir)].sort((a, b) => key(a) < key(b) ? (rev ? 1 : -1) : key(a) > key(b) ? (rev ? -1 : 1) : 0)
    const files = [...entries.filter(e => !e.is_dir)].sort((a, b) => key(a) < key(b) ? (rev ? 1 : -1) : key(a) > key(b) ? (rev ? -1 : 1) : 0)
    return dirs.concat(files)
  })

  // 2. Navigazione e Storia
  function pushHistory(path) {
    if (!path) return
    const current = fileHistory.value[fileHistoryIndex.value]
    if (current === path) return
    fileHistory.value = fileHistory.value.slice(0, fileHistoryIndex.value + 1)
    fileHistory.value.push(path)
    fileHistoryIndex.value = fileHistory.value.length - 1
  }

  async function loadFileRoots() {
    if (!apiReady.value) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/files/default-root'))
      fileDefaultPath.value = data?.default_path || '/home/gufobox/media'
      fileAllowedRoots.value = data?.allowed_roots || []
      if (!fileCurrentPath.value) fileCurrentPath.value = fileDefaultPath.value
    } catch (_) {}
  }

  async function loadFileList(path = fileCurrentPath.value, { addToHistory = true } = {}) {
    if (!apiReady.value) return
    fileLoading.value = true
    fileError.value = ''
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/files/list', { params: { path } }))
      fileCurrentPath.value = data?.current_path || fileDefaultPath.value
      fileEntries.value = data?.entries || []
      fileDefaultPath.value = data?.default_path || fileDefaultPath.value
      fileAllowedRoots.value = data?.allowed_roots || fileAllowedRoots.value
      selectedFilePaths.value = []
      fileSearch.value = ''
      if (addToHistory) pushHistory(fileCurrentPath.value)
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore lettura cartella')
    } finally {
      fileLoading.value = false
    }
  }

  async function goFileHome() { await loadFileList(fileDefaultPath.value, { addToHistory: true }) }
  async function goFileUp() { await loadFileList(fileParentPath.value, { addToHistory: true }) }
  async function goFileBack() {
    if (!canGoBack.value) return
    fileHistoryIndex.value -= 1
    await loadFileList(fileHistory.value[fileHistoryIndex.value], { addToHistory: false })
  }
  async function goFileForward() {
    if (!canGoForward.value) return
    fileHistoryIndex.value += 1
    await loadFileList(fileHistory.value[fileHistoryIndex.value], { addToHistory: false })
  }

  // Multi-select: ogni click toglie o aggiunge
  function toggleFileSelection(path) {
    const idx = selectedFilePaths.value.indexOf(path)
    if (idx >= 0) {
      selectedFilePaths.value = selectedFilePaths.value.filter(p => p !== path)
    } else {
      selectedFilePaths.value = [...selectedFilePaths.value, path]
    }
  }

  function selectAll() {
    selectedFilePaths.value = filteredEntries.value.map(e => e.path)
  }

  function clearSelection() {
    selectedFilePaths.value = []
  }

  // 3. Azioni sui File
  async function createFolder(onSuccess) {
    if (!newFolderName.value.trim()) return
    try {
      const api = getApi()
      await guardedCall(() => api.post('/files/mkdir', { path: fileCurrentPath.value, name: newFolderName.value }))
      newFolderName.value = ''
      await loadFileList(fileCurrentPath.value, { addToHistory: false })
      if (onSuccess) onSuccess('Cartella creata')
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore creazione cartella')
    }
  }

  async function renameEntry(entry, newName) {
    if (!newName || newName === entry.name) return
    try {
      const api = getApi()
      await guardedCall(() => api.post('/files/rename', { path: entry.path, new_name: newName }))
      await loadFileList(fileCurrentPath.value, { addToHistory: false })
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore rinomina')
    }
  }

  function moveSelected() {
    if (!selectedFilePaths.value.length) return
    clipboardMode.value = 'move'
    clipboardPaths.value = [...selectedFilePaths.value]
  }

  function copySelected() {
    if (!selectedFilePaths.value.length) return
    clipboardMode.value = 'copy'
    clipboardPaths.value = [...selectedFilePaths.value]
  }

  function clearClipboard() {
    clipboardMode.value = ''
    clipboardPaths.value = []
  }

  async function pasteClipboard(onJobCreated) {
    if (!clipboardMode.value || !clipboardPaths.value.length) return
    try {
      const api = getApi()
      let data
      if (clipboardMode.value === 'copy') {
        ;({ data } = await guardedCall(() => api.post('/files/copy', { sources: clipboardPaths.value, destination: fileCurrentPath.value })))
      } else {
        ;({ data } = await guardedCall(() => api.post('/files/move', { sources: clipboardPaths.value, destination: fileCurrentPath.value })))
      }
      clipboardMode.value = ''
      clipboardPaths.value = []
      if (data?.job?.job_id && onJobCreated) await onJobCreated(data.job)
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore incolla')
    }
  }

  async function deleteSelected(onJobCreated) {
    if (!selectedFilePaths.value.length) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/files/delete', { paths: selectedFilePaths.value }))
      selectedFilePaths.value = []
      if (onJobCreated) await onJobCreated({ deleted: data?.deleted, errors: data?.errors })
      await loadFileList(fileCurrentPath.value, { addToHistory: false })
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore cancellazione')
    }
  }

  async function compressSelected(archiveName, onJobCreated) {
    if (!selectedFilePaths.value.length || !archiveName) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/files/compress', {
        paths: selectedFilePaths.value,
        destination: fileCurrentPath.value,
        archive_name: archiveName
      }))
      if (data?.job?.job_id && onJobCreated) await onJobCreated(data.job)
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore compressione')
    }
  }

  async function uncompressEntry(entry, onJobCreated) {
    if (!entry?.path) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/files/uncompress', {
        path: entry.path,
        destination: fileCurrentPath.value,
      }))
      if (data?.job?.job_id && onJobCreated) await onJobCreated(data.job)
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore decompressione')
    }
  }

  // 4. Upload a Chunk con progress per file
  async function uploadFiles(ev, onJobCreated) {
    const files = [...(ev.target.files || [])]
    if (!files.length) return

    const api = getApi()

    for (const file of files) {
      const queueEntry = { name: file.name, progress: 0, status: 'uploading', error: '' }
      uploadQueue.value = [...uploadQueue.value, queueEntry]
      const qi = uploadQueue.value.length - 1

      try {
        const initResp = await guardedCall(() => api.post('/files/upload/init', {
          filename: file.name,
          total_size: file.size,
          path: fileCurrentPath.value,
          chunk_size: 8 * 1024 * 1024,
        }))

        const sessionId = initResp.data?.session_id
        const chunkSize = Number(initResp.data?.chunk_size || 8 * 1024 * 1024)
        if (!sessionId) throw new Error('session_id mancante')

        let offset = 0
        while (offset < file.size) {
          const blob = file.slice(offset, offset + chunkSize)
          const form = new FormData()
          form.append('session_id', sessionId)
          form.append('offset', String(offset))
          form.append('chunk', blob, file.name)

          await guardedCall(() => api.post('/files/upload/chunk', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 120000,
          }))
          offset += blob.size
          const pct = file.size > 0 ? Math.round((offset / file.size) * 100) : 100
          uploadQueue.value[qi] = { ...uploadQueue.value[qi], progress: pct }
        }

        const finalResp = await guardedCall(() => api.post('/files/upload/finalize', { session_id: sessionId }))
        uploadQueue.value[qi] = { ...uploadQueue.value[qi], progress: 100, status: 'done' }

        if (onJobCreated) await onJobCreated({ filename: file.name, path: finalResp?.data?.path })
        await loadFileList(fileCurrentPath.value, { addToHistory: false })
      } catch (e) {
        const errMsg = extractApiError(e, 'Errore upload')
        uploadQueue.value[qi] = { ...uploadQueue.value[qi], status: 'error', error: errMsg }
      }
    }
    ev.target.value = ''

    // Rimuovi le voci completate dopo 4s
    setTimeout(() => {
      uploadQueue.value = uploadQueue.value.filter(q => q.status !== 'done')
    }, UPLOAD_DONE_CLEAR_MS)
  }

  // 5. Preview dei file
  function isPreviewable(entry) {
    return ['image', 'audio', 'video'].includes(entry?.type)
  }

  function revokePreviewUrl() {
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl)
      previewObjectUrl = null
    }
  }

  function closePreview() {
    previewOpen.value = false
    previewFile.value = null
    previewUrl.value = ''
    previewLoading.value = false
    revokePreviewUrl()
  }

  async function openPreview(entry) {
    if (!entry?.path || !apiReady.value) return
    previewOpen.value = true
    previewLoading.value = true
    previewFile.value = entry
    previewUrl.value = ''
    revokePreviewUrl()

    try {
      const api = getApi()
      const response = await guardedCall(() =>
        api.get('/files/open', { params: { path: entry.path }, responseType: 'blob', timeout: 120000 })
      )

      const blobType = response?.data?.type || 'application/octet-stream'
      const blob = new Blob([response.data], { type: blobType })
      previewObjectUrl = URL.createObjectURL(blob)
      previewUrl.value = previewObjectUrl
    } catch (e) {
      closePreview()
      fileError.value = extractApiError(e, 'Errore apertura file')
    } finally {
      previewLoading.value = false
    }
  }

  function openEntry(entry) {
    if (entry?.is_dir) {
      loadFileList(entry.path, { addToHistory: true })
      return
    }
    if (isPreviewable(entry)) openPreview(entry)
  }

  // 6. Menu e Dettagli
  function openFileMenu(entry) {
    if (!entry) return
    fileMenuTarget.value = entry
    fileMenuOpen.value = true
  }

  function closeFileMenu() {
    fileMenuOpen.value = false
    fileMenuTarget.value = null
  }

  async function fetchDetails(path) {
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/files/details', { path }))
      return data
    } catch (e) {
      fileError.value = extractApiError(e, 'Errore dettagli')
      return null
    }
  }

  return {
    // Stato
    fileCurrentPath, fileEntries, fileLoading, fileError,
    selectedFilePaths, newFolderName,
    clipboardMode, clipboardPaths,
    fileMenuOpen, fileMenuTarget,
    previewOpen, previewFile, previewUrl, previewLoading,
    fileSearch, fileSortBy, fileSortOrder, fileFilterType,
    uploadQueue,

    // Computed
    selectedCount, canGoBack, canGoForward, fileParentPath, breadcrumbs,
    filteredEntries,

    // Navigazione
    loadFileRoots, loadFileList, goFileHome, goFileUp, goFileBack, goFileForward,
    toggleFileSelection, selectAll, clearSelection, openEntry,

    // Azioni file
    createFolder, renameEntry,
    moveSelected, copySelected, clearClipboard, pasteClipboard,
    deleteSelected, compressSelected, uncompressEntry,
    uploadFiles,
    fetchDetails,

    // Preview e Menu
    isPreviewable, openPreview, closePreview, revokePreviewUrl,
    openFileMenu, closeFileMenu,
  }
}

