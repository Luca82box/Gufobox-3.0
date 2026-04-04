<template>
  <div class="home-view">

    <!-- ═══════════════════════════════════════════════════
         PLAYER CARD
    ═══════════════════════════════════════════════════ -->
    <div v-if="mediaStatus && !rssPreview" class="player-card">

      <!-- Copertina -->
      <div class="cover-wrapper">
        <img
          v-if="mediaStatus.cover_url"
          :src="mediaStatus.cover_url"
          alt="Copertina"
          class="album-cover"
        />
        <div v-else class="album-placeholder">🎵</div>
      </div>

      <!-- Titolo e sottotitolo -->
      <div class="track-info">
        <h2 class="track-title">{{ mediaStatus.title || 'Nessun titolo' }}</h2>
        <p class="track-sub">{{ currentProfile ? currentProfile : 'In riproduzione' }}</p>
      </div>

      <!-- Controlli di trasporto -->
      <div class="transport-bar">
        <button class="ctrl-btn" @click="mediaPrev" title="Precedente">⏮</button>
        <button class="ctrl-btn ctrl-btn--play" @click="mediaTogglePause" title="Play/Pausa">
          {{ mediaStatus.is_paused ? '▶' : '⏸' }}
        </button>
        <button class="ctrl-btn" @click="mediaNext" title="Successivo">⏭</button>
      </div>

      <!-- Barra di progresso -->
      <div class="progress-container">
        <span class="time-label">{{ progressCurrent }}</span>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <span class="time-label">{{ progressTotal }}</span>
      </div>

      <!-- Barra volume -->
      <div class="volume-bar">
        <span class="vol-icon">🔈</span>
        <input
          type="range"
          min="0" max="100"
          v-model="currentVolume"
          @input="onVolumeInput"
          class="vol-slider"
        />
        <span class="vol-icon">🔊</span>
      </div>

    </div>

    <!-- ═══════════════════════════════════════════════════
         RSS
    ═══════════════════════════════════════════════════ -->
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

    <!-- ═══════════════════════════════════════════════════
         EMPTY STATE
    ═══════════════════════════════════════════════════ -->
    <div v-if="!mediaStatus && !rssPreview" class="empty-state">
      <div class="owl-sleeping">🦉💤</div>
      <p>Avvicina una statuina magica per iniziare!</p>
    </div>

    <!-- ═══════════════════════════════════════════════════
         PANNELLO CHAT AI (visibile solo se showAiChat)
    ═══════════════════════════════════════════════════ -->
    <Transition name="slide-up">
      <div v-if="showAiChat" class="chat-card">

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
            :class="['btn-mic', { listening: isListening }]"
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

          <button @click="() => sendAiMessage()" class="btn-send" :disabled="!aiInputText.trim()" aria-label="Invia messaggio">
            🚀
          </button>
        </div>

      </div>
    </Transition>

  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import { useMedia } from '../composables/useMedia'
import { useAi } from '../composables/useAi'
import { useAuth } from '../composables/useAuth'

const {
  mediaStatus, currentProfile, currentVolume, rssPreview,
  loadMediaStatus, onVolumeInput, mediaPrev, mediaNext, mediaStop, mediaTogglePause,
  progressCurrent, progressTotal, progressPercent
} = useMedia()

const {
  aiRuntime, aiInputText, isListening, speechSupported,
  initSpeechRecognition, toggleListening, sendAiMessage, stopAiAudio
} = useAi()

const { showAiChat } = useAuth()

const chatHistoryRef = ref(null)

watch(() => aiRuntime.value?.history, async () => {
  await nextTick()
  if (chatHistoryRef.value) {
    chatHistoryRef.value.scrollTop = chatHistoryRef.value.scrollHeight
  }
}, { deep: true })

let pollingTimer = null

onMounted(() => {
  initSpeechRecognition()
  loadMediaStatus()
  pollingTimer = setInterval(() => { loadMediaStatus() }, 1000)
})

onBeforeUnmount(() => {
  if (pollingTimer) clearInterval(pollingTimer)
})
</script>

<style scoped>
/* ─── Layout ──────────────────────────────────────────────── */
.home-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 16px;
  max-width: 480px;
  margin: 0 auto;
}

/* ─── Player Card ─────────────────────────────────────────── */
.player-card {
  width: 100%;
  background: rgba(20, 20, 48, 0.72);
  border-radius: 20px;
  padding: 20px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  border: 1px solid rgba(255,255,255,0.06);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

/* ─── Copertina ───────────────────────────────────────────── */
.cover-wrapper {
  width: 100%;
  max-width: 300px;
  aspect-ratio: 1;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
}

.album-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.album-placeholder {
  width: 100%;
  height: 100%;
  background: rgba(63,81,181,0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 4rem;
}

/* ─── Titolo ──────────────────────────────────────────────── */
.track-info {
  text-align: center;
  width: 100%;
}

.track-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.track-sub {
  margin: 4px 0 0;
  font-size: 0.85rem;
  color: #ff9800;
  font-weight: 600;
}

/* ─── Barra trasporto ─────────────────────────────────────── */
.transport-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: linear-gradient(135deg, #ff9800, #ff6d00);
  border-radius: 50px;
  padding: 10px 28px;
  width: 100%;
  box-shadow: 0 4px 16px rgba(255,109,0,0.4);
}

.ctrl-btn {
  background: rgba(255,255,255,0.18);
  border: none;
  border-radius: 50%;
  width: 44px;
  height: 44px;
  font-size: 1.3rem;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.18s, transform 0.15s;
}

.ctrl-btn:hover {
  background: rgba(255,255,255,0.32);
  transform: scale(1.1);
}

.ctrl-btn--play {
  width: 56px;
  height: 56px;
  font-size: 1.6rem;
  background: rgba(255,255,255,0.28);
  box-shadow: 0 2px 10px rgba(0,0,0,0.25);
}

/* ─── Progress bar ────────────────────────────────────────── */
.progress-container {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.time-label {
  font-size: 0.75rem;
  color: rgba(255,255,255,0.6);
  min-width: 36px;
  text-align: center;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: rgba(255,255,255,0.12);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #ff9800;
  border-radius: 3px;
  transition: width 0.4s linear;
}

/* ─── Volume bar ──────────────────────────────────────────── */
.volume-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.vol-icon {
  font-size: 1.1rem;
  flex-shrink: 0;
}

.vol-slider {
  flex: 1;
  accent-color: #ff9800;
  height: 4px;
}

/* ─── Empty state ─────────────────────────────────────────── */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: rgba(255,255,255,0.6);
}

.owl-sleeping {
  font-size: 4rem;
  animation: doze 3s ease-in-out infinite alternate;
  margin-bottom: 12px;
}

@keyframes doze {
  from { transform: translateY(0) rotate(-3deg); }
  to   { transform: translateY(-8px) rotate(3deg); }
}

/* ─── RSS card ────────────────────────────────────────────── */
.rss-card {
  width: 100%;
  background: rgba(20,20,48,0.72);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 4px 15px rgba(0,0,0,0.3);
}

.rss-scroll-area {
  max-height: 280px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 12px;
}

.rss-item {
  padding: 8px;
  background: rgba(255,255,255,0.05);
  border-radius: 8px;
  font-size: 0.9rem;
}

.btn-stop-rss {
  background: rgba(255,77,77,0.2);
  border: 1px solid rgba(255,77,77,0.5);
  color: #ff8a80;
  border-radius: 8px;
  padding: 8px 16px;
  cursor: pointer;
  font-size: 0.9rem;
  width: 100%;
}

/* ─── Chat AI card ────────────────────────────────────────── */
.chat-card {
  width: 100%;
  background: rgba(20,20,48,0.82);
  border-radius: 20px;
  padding: 16px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  border: 1px solid rgba(63,81,181,0.3);
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.chat-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #fff;
}

.btn-stop-ai {
  background: rgba(255,77,77,0.2);
  border: 1px solid rgba(255,77,77,0.4);
  color: #ff8a80;
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 0.8rem;
}

.chat-history {
  height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px;
  background: rgba(10,10,30,0.5);
  border-radius: 10px;
}

.chat-bubble {
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 0.88rem;
  max-width: 85%;
  word-break: break-word;
}

.bubble-user {
  align-self: flex-end;
  background: #4caf50;
  border-radius: 12px 12px 0 12px;
  color: #fff;
}

.bubble-ai {
  align-self: flex-start;
  background: #3f51b5;
  border-radius: 12px 12px 12px 0;
  color: #fff;
}

.thinking {
  opacity: 0.7;
  font-style: italic;
}

.chat-input-area {
  display: flex;
  gap: 8px;
  align-items: center;
}

.chat-input-area input {
  flex: 1;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 8px;
  padding: 8px 12px;
  color: #fff;
  font-size: 0.9rem;
}

.chat-input-area input::placeholder {
  color: rgba(255,255,255,0.35);
}

.btn-mic {
  background: rgba(63,81,181,0.3);
  border: 1px solid rgba(63,81,181,0.5);
  border-radius: 50%;
  width: 38px;
  height: 38px;
  font-size: 1.1rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.btn-mic.listening {
  background: rgba(255,68,68,0.4);
  border-color: #ff4444;
  animation: pulse 1s infinite;
}

.btn-send {
  background: rgba(255,152,0,0.25);
  border: 1px solid rgba(255,152,0,0.5);
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 1rem;
  flex-shrink: 0;
}

.btn-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

@keyframes pulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.1); }
  100% { transform: scale(1); }
}

/* ─── Transition ──────────────────────────────────────────── */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: opacity 0.3s, transform 0.3s;
}
.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(20px);
}
</style>

