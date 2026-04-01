<template>
  <div class="admin-file-manager">
    
    <div class="toolbar">
      <div class="breadcrumbs">
        <button class="btn-icon" @click="goFileHome" title="Home">🏠</button>
        <button class="btn-icon" @click="goFileUp" title="Su" :disabled="!fileParentPath">⬆️</button>
        <span class="path-display">{{ fileCurrentPath }}</span>
      </div>

      <div class="actions">
        <button class="btn-action" @click="createFolder">📁 Nuova Cartella</button>
        
        <input 
          type="file" 
          multiple 
          ref="fileInputRef" 
          style="display: none" 
          @change="(e) => uploadFiles(e, onUploadJobCreated)" 
        />
        <button class="btn-action btn-upload" @click="$refs.fileInputRef.click()">
          📤 Carica File
        </button>
      </div>
    </div>

    <div v-if="selectedCount > 0 || clipboardPaths.length > 0" class="selection-toolbar">
      <span v-if="selectedCount > 0">{{ selectedCount }} elementi selezionati</span>
      <span v-if="clipboardPaths.length > 0">📋 {{ clipboardPaths.length }} elementi in appunti ({{ clipboardMode }})</span>

      <div class="selection-actions">
        <button v-if="selectedCount > 0" @click="copySelected">Copia</button>
        <button v-if="selectedCount > 0" @click="moveSelected">Taglia</button>
        <button v-if="clipboardPaths.length > 0" @click="() => pasteClipboard(onJobCreated)" class="btn-paste">Incolla Qui</button>
        <button v-if="selectedCount > 0" @click="() => deleteSelected(onJobCreated)" class="btn-danger">Elimina</button>
        <button v-if="selectedCount > 0" @click="() => compressSelected(onJobCreated)">Zippa</button>
      </div>
    </div>

    <div class="file-list">
      <div v-if="fileEntries.length === 0" class="empty-folder">
        La cartella è vuota 🕸️
      </div>

      <div 
        v-for="entry in fileEntries" 
        :key="entry.path"
        class="file-item"
        :class="{ 'selected': selectedFilePaths.includes(entry.path) }"
      >
        <input 
          type="checkbox" 
          :checked="selectedFilePaths.includes(entry.path)"
          @change="toggleFileSelection(entry.path)"
        />

        <div class="entry-info" @click="openEntry(entry)">
          <span class="icon">{{ entry.is_dir ? '📁' : (isPreviewable(entry) ? '🖼️' : '📄') }}</span>
          <span class="name">{{ entry.name }}</span>
        </div>

        <div class="entry-size" v-if="!entry.is_dir">
          {{ formatBytes(entry.size) }}
        </div>

        <div class="entry-menu">
          <button class="btn-icon" @click="renameEntry(entry)" title="Rinomina">✏️</button>
          <button class="btn-icon" @click="showDetails(entry.path)" title="Dettagli">ℹ️</button>
        </div>
      </div>
    </div>

    <div v-if="previewOpen" class="preview-modal" @click.self="closePreview">
      <div class="preview-content">
        <div class="preview-header">
          <h3>{{ previewFile?.name }}</h3>
          <button class="btn-icon" @click="closePreview">✖</button>
        </div>
        
        <div class="preview-body">
          <div v-if="previewLoading" class="loading">Caricamento in corso... ⏳</div>
          <template v-else-if="previewUrl">
            <img v-if="previewFile.type === 'image'" :src="previewUrl" class="preview-media" />
            <audio v-else-if="previewFile.type === 'audio'" :src="previewUrl" controls autoplay class="preview-media"></audio>
            <video v-else-if="previewFile.type === 'video'" :src="previewUrl" controls autoplay class="preview-media"></video>
            <div v-else>Anteprima non supportata per questo formato.</div>
          </template>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useFileManager } from '../../composables/useFileManager'

const {
  fileCurrentPath, fileParentPath, fileEntries, selectedFilePaths,
  clipboardMode, clipboardPaths, selectedCount,
  previewOpen, previewFile, previewUrl, previewLoading,
  loadFileList, loadFileRoots, goFileHome, goFileUp,
  toggleFileSelection, openEntry, closePreview, isPreviewable,
  createFolder, renameEntry, moveSelected, copySelected, pasteClipboard,
  deleteSelected, compressSelected, uploadFiles, showDetails
} = useFileManager()

const fileInputRef = ref(null)

// Utility per formattare i byte in KB/MB
function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

// Callback fittizie per i Job (in futuro le collegheremo alle notifiche toast)
async function onJobCreated() {
  alert('Operazione avviata in background!')
}

async function onUploadJobCreated() {
  alert('Upload completato!')
}

onMounted(async () => {
  await loadFileRoots()
  await loadFileList()
})
</script>

<style scoped>
.admin-file-manager {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.toolbar, .selection-toolbar {
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
  gap: 10px;
}

.path-display {
  font-family: monospace;
  color: #ffd27b;
  background: #1e1e26;
  padding: 5px 10px;
  border-radius: 4px;
}

.actions, .selection-actions {
  display: flex;
  gap: 10px;
}

.btn-action, .selection-actions button {
  background: #3f51b5;
  color: white;
  border: none;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-weight: bold;
}

.btn-action.btn-upload { background: #4caf50; }
.btn-paste { background: #ff9800 !important; }
.btn-danger { background: #ff4d4d !important; }

.btn-icon {
  background: transparent;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  color: #fff;
}

.file-list {
  background: #2a2a35;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.file-item {
  display: grid;
  grid-template-columns: 40px 1fr auto 80px;
  align-items: center;
  padding: 10px 15px;
  border-bottom: 1px solid #3a3a48;
  transition: background 0.2s;
}

.file-item:hover, .file-item.selected {
  background: #3a3a48;
}

.entry-info {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.icon { font-size: 1.5rem; }
.name { font-weight: 500; }
.entry-size { color: #aaa; font-size: 0.9rem; text-align: right; padding-right: 15px; }

.empty-folder {
  padding: 30px;
  text-align: center;
  color: #aaa;
}

/* Modale Preview */
.preview-modal {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.preview-content {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 15px;
}

.preview-media {
  max-width: 100%;
  max-height: 70vh;
  border-radius: 8px;
}
</style>

