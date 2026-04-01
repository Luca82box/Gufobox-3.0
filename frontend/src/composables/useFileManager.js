import { ref, computed } from 'vue'
import { useApi } from './useApi'

// Stato condiviso
const fileCurrentPath = ref('/home/gufobox/media')
const fileDefaultPath = ref('/home/gufobox/media')
const fileAllowedRoots = ref([])
const fileEntries = ref([])
const selectedFilePaths = ref([])
const newFolderName = ref('')

const clipboardMode = ref('')
const clipboardPaths = ref([])

const fileHistory = ref([])
const fileHistoryIndex = ref(-1)

// Stato Menu e Preview
const fileMenuOpen = ref(false)
const fileMenuTarget = ref(null)
const previewOpen = ref(false)
const previewFile = ref(null)
const previewUrl = ref('')
const previewLoading = ref(false)
let previewObjectUrl = null

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
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.get('/files/list', { params: { path } }))
      fileCurrentPath.value = data?.current_path || fileDefaultPath.value
      fileEntries.value = data?.entries || []
      fileDefaultPath.value = data?.default_path || fileDefaultPath.value
      fileAllowedRoots.value = data?.allowed_roots || fileAllowedRoots.value
      selectedFilePaths.value = []
      if (addToHistory) pushHistory(fileCurrentPath.value)
    } catch (e) {
      alert(extractApiError(e, 'Errore lettura cartella'))
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

  function toggleFileSelection(path) {
    if (selectedFilePaths.value.includes(path)) {
      selectedFilePaths.value = selectedFilePaths.value.filter(p => p !== path)
    } else {
      selectedFilePaths.value = [path] // Sostituisci con .push(path) se vuoi selezione multipla libera
    }
  }

  // 3. Azioni sui File (Crea, Rinomina, Copia, Elimina, ecc.)
  async function createFolder() {
    if (!newFolderName.value.trim()) return alert('Nome cartella mancante')
    try {
      const api = getApi()
      await guardedCall(() => api.post('/files/mkdir', { path: fileCurrentPath.value, name: newFolderName.value }))
      newFolderName.value = ''
      await loadFileList(fileCurrentPath.value, { addToHistory: false })
    } catch (e) {
      alert(extractApiError(e, 'Errore creazione cartella'))
    }
  }

  async function renameEntry(entry) {
    const newName = prompt('Nuovo nome:', entry.name)
    if (!newName) return
    try {
      const api = getApi()
      await guardedCall(() => api.post('/files/rename', { path: entry.path, new_name: newName }))
      await loadFileList(fileCurrentPath.value, { addToHistory: false })
    } catch (e) {
      alert(extractApiError(e, 'Errore rinomina'))
    }
  }

  function moveSelected() {
    if (!selectedFilePaths.value.length) return alert('Seleziona un elemento')
    clipboardMode.value = 'move'
    clipboardPaths.value = [...selectedFilePaths.value]
    alert('Vai nella cartella destinazione e premi Incolla.')
  }

  function copySelected() {
    if (!selectedFilePaths.value.length) return alert('Seleziona un elemento')
    clipboardMode.value = 'copy'
    clipboardPaths.value = [...selectedFilePaths.value]
    alert('Vai nella cartella destinazione e premi Incolla.')
  }

  async function pasteClipboard(onJobCreated) {
    if (!clipboardMode.value || !clipboardPaths.value.length) return alert('Clipboard vuota')
    try {
      const api = getApi()
      let data
      if (clipboardMode.value === 'copy') {
        ({ data } = await guardedCall(() => api.post('/files/copy', { sources: clipboardPaths.value, destination: fileCurrentPath.value })))
      } else {
        ({ data } = await guardedCall(() => api.post('/files/move', { sources: clipboardPaths.value, destination: fileCurrentPath.value })))
      }
      clipboardMode.value = ''
      clipboardPaths.value = []
      
      if (data?.job?.job_id && onJobCreated) await onJobCreated()
      else if (!data?.job?.job_id) alert('Operazione inviata, ma il backend non ha restituito un job')
    } catch (e) {
      alert(extractApiError(e, 'Errore incolla'))
    }
  }

  async function deleteSelected(onJobCreated) {
    if (!selectedFilePaths.value.length) return alert('Seleziona un elemento')
    if (!confirm(`Eliminare ${selectedFilePaths.value.length} elemento/i?`)) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/files/delete', { paths: selectedFilePaths.value }))
      selectedFilePaths.value = []
      if (data?.job?.job_id && onJobCreated) await onJobCreated()
      else if (!data?.job?.job_id) alert('Eliminazione inviata, ma il backend non ha restituito un job')
    } catch (e) {
      alert(extractApiError(e, 'Errore cancellazione'))
    }
  }

  async function compressSelected(onJobCreated) {
    if (!selectedFilePaths.value.length) return alert('Seleziona un elemento')
    const archiveName = prompt('Nome archivio zip:', 'archivio')
    if (!archiveName) return
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/files/compress', {
        paths: selectedFilePaths.value,
        destination: fileCurrentPath.value,
        archive_name: archiveName
      }))
      if (data?.job?.job_id && onJobCreated) await onJobCreated()
      else if (!data?.job?.job_id) alert('Compressione inviata, ma il backend non ha restituito un job')
    } catch (e) {
      alert(extractApiError(e, 'Errore compressione'))
    }
  }

  // 4. Upload a Chunk (Il blocco più pesante!)
  async function uploadFiles(ev, onJobCreated) {
    const files = [...(ev.target.files || [])]
    if (!files.length) return

    const api = getApi()

    for (const file of files) {
      try {
        const initResp = await guardedCall(() => api.post('/files/upload/init', {
          filename: file.name,
          total_size: file.size,
          path: fileCurrentPath.value,
          chunk_size: 8 * 1024 * 1024
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
            timeout: 120000
          }))
          offset += blob.size
        }

        await guardedCall(() => api.post('/files/upload/finalize', { session_id: sessionId }))
        
        if (onJobCreated) await onJobCreated()
        await loadFileList(fileCurrentPath.value, { addToHistory: false })
      } catch (e) {
        alert(`${file.name}: ${extractApiError(e, 'Errore upload chunked')}`)
        break
      }
    }
    ev.target.value = ''
  }

  // 5. Preview dei file (Audio, Immagini, Video)
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
      alert(extractApiError(e, 'Errore apertura file'))
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

  // 6. Menu a Tendina e Callback Form
  function openFileMenu(entry) {
    if (!entry) return
    fileMenuTarget.value = entry
    fileMenuOpen.value = true
  }

  function closeFileMenu() {
    fileMenuOpen.value = false
    fileMenuTarget.value = null
  }

  async function showDetails(path) {
    try {
      const api = getApi()
      const { data } = await guardedCall(() => api.post('/files/details', { path }))
      alert(`Dettagli:\nNome: ${data.name}\nTipo: ${data.type}\nSize: ${data.size}\nPath: ${data.path}`)
    } catch (e) {
      alert(extractApiError(e, 'Errore dettagli'))
    }
  }

  return {
    // Stato
    fileCurrentPath, fileEntries, selectedFilePaths, newFolderName,
    clipboardMode, clipboardPaths, fileMenuOpen, fileMenuTarget,
    previewOpen, previewFile, previewUrl, previewLoading,

    // Computed
    selectedCount, canGoBack, canGoForward, fileParentPath, breadcrumbs,

    // Metodi Navigazione e Ricarica
    loadFileRoots, loadFileList, goFileHome, goFileUp, goFileBack, goFileForward,
    toggleFileSelection, openEntry, 

    // Metodi Azione File
    createFolder, renameEntry, moveSelected, copySelected, pasteClipboard,
    deleteSelected, compressSelected, uploadFiles, showDetails,

    // Metodi Preview e Menu
    isPreviewable, openPreview, closePreview, revokePreviewUrl, openFileMenu, closeFileMenu
  }
}

