<template>
  <div class="home-view">
    
    <div class="media-section">
      
      <div v-if="mediaStatus && !rssPreview" class="player-card">
        <div class="cover-wrapper">
          <img 
            v-if="mediaStatus.cover_url" 
            :src="mediaStatus.cover_url" 
            alt="Copertina" 
            class="album-cover" 
          />
          <div v-else class="album-placeholder">🎵</div>
        </div>

        <div class="track-info">
          <h2>{{ mediaStatus.title || 'Nessun titolo' }}</h2>
          <p>{{ currentProfile ? `Profilo: ${currentProfile}` : 'In riproduzione' }}</p>
        </div>

        <div class="progress-container">
          <span class="time">{{ progressCurrent }}</span>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
          </div>
          <span class="time">{{ progressTotal }}</span>
        </div>

        <div class="controls">
          <button @click="mediaPrev" class="btn-control">⏮️</button>
          <button @click="mediaStop" class="btn-control btn-stop">⏹️</button>
          <button @click="mediaNext" class="btn-control">⏭️</button>
        </div>

        <div class="volume-control">
          <span>🔈</span>
          <input 
            type="range" 
            min="0" max="100" 
            v-model="currentVolume" 
            @input="onVolumeInput"
          />
          <span>🔊</span>
        </div>
      </div>

      <div v-if="rssPreview" class="rss-card">
        <h2>📰 Ultime Notizie</h2>
        <div class="rss-scroll-area">
          <div v-for="(item, idx) in rssPreview.entries" :key="idx" class="rss-item">
            <strong>{{ item.title }}</strong>
            <p v-if="item.summary">{{ item.summary }}</p>
          </div>
        </div>
        <button @click="mediaStop" class="btn-stop-rss">Chiudi Notizie ⏹️</button>
      </div>

      <div v-if="!mediaStatus && !rssPreview" class="empty-state">
        <div class="owl-sleeping">🦉💤</div>
        <p>Avvicina una statuina magica per iniziare!</p>
      </div>

    </div>

    <div class="ai-section">
      <div class="chat-card">
        
        <div class="chat-header">
          <h3>Il Gufetto Magico 🦉</h3>
          <button v-if="aiRuntime?.is_speaking" @click="stopAiAudio" class="btn-stop-ai">
            Muta 🤫
          </button>
        </div>

        <div class="chat-history" ref="chatHistoryRef">
          <div 
            v-for="(msg, idx) in (aiRuntime?.history || [])" 
            :key="idx" 
            :class="['chat-bubble', msg.role === 'user' ? 'bubble-user' : 'bubble-ai']"
          >
            {{ msg.content }}
          </div>
          <div v-if="aiRuntime?.is_thinking" class="chat-bubble bubble-ai thinking">
            Il gufetto sta pensando... 💭
          </div>
        </div>

        <div class="chat-input-area">
          <button 
            @click="toggleListening" 
            :class="['btn-mic', { 'listening': isListening }]"
            :disabled="!speechSupported"
            title="Parla col Gufetto"
          >
            {{ isListening ? '🔴' : '🎤' }}
          </button>
          
          <input 
            type="text" 
            v-model="aiInputText" 
            @keyup.enter="() => sendAiMessage()"
            placeholder="Chiedi qualcosa al gufetto..." 
          />
          
          <button @click="() => sendAiMessage()" class="btn-send" :disabled="!aiInputText.trim()">
            Invia 🚀
          </button>
        </div>

      </div>
    </div>

  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import { useMedia } from '../composables/useMedia'
import { useAi } from '../composables/useAi'

// 1. Importiamo la logica dai nostri composables
const {
  mediaStatus, currentProfile, currentVolume, rssPreview,
  loadMediaStatus, onVolumeInput, mediaPrev, mediaNext, mediaStop,
  progressCurrent, progressTotal, progressPercent
} = useMedia()

const {
  aiRuntime, aiInputText, isListening, speechSupported,
  initSpeechRecognition, toggleListening, sendAiMessage, stopAiAudio
} = useAi()

// 2. Riferimenti per l'interfaccia (es. auto-scroll della chat)
const chatHistoryRef = ref(null)

watch(() => aiRuntime.value?.history, async () => {
  await nextTick()
  if (chatHistoryRef.value) {
    chatHistoryRef.value.scrollTop = chatHistoryRef.value.scrollHeight
  }
}, { deep: true })

// 3. Ciclo di vita del componente
let pollingTimer = null

onMounted(() => {
  // Inizializza il microfono
  initSpeechRecognition()
  
  // Carica lo stato iniziale
  loadMediaStatus()

  // Avvia il polling per aggiornare la barra di progresso e lo stato AI ogni secondo
  // (In alternativa, questo può essere gestito dal Socket.io in App.vue, ma qui è un fallback sicuro)
  pollingTimer = setInterval(() => {
    loadMediaStatus()
  }, 1000)
})

onBeforeUnmount(() => {
  if (pollingTimer) clearInterval(pollingTimer)
})
</script>

<style scoped>
/* Qui andrà incollato il CSS relativo a .player-card, .chat-card, ecc. dal tuo file originale */
.home-view {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
}

@media (min-width: 860px) {
  .home-view {
    grid-template-columns: 1fr 1fr; /* Player a sinistra, Chat a destra su schermi grandi */
  }
}

.player-card, .chat-card, .rss-card, .empty-state {
  background: var(--surface, #2a2a35);
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 4px 15px rgba(0,0,0,0.2);
}

/* ... Aggiungi qui le altre classi CSS per bottoni, progress bar e chat bubbles ... */
.chat-history {
  height: 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 15px;
  padding: 10px;
  background: #1e1e26;
  border-radius: 8px;
}

.bubble-user { align-self: flex-end; background: #4caf50; padding: 10px; border-radius: 12px 12px 0 12px; }
.bubble-ai { align-self: flex-start; background: #3f51b5; padding: 10px; border-radius: 12px 12px 12px 0; }
.btn-mic.listening { animation: pulse 1s infinite; background: #ff4444; }

@keyframes pulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.1); }
  100% { transform: scale(1); }
}
</style>

