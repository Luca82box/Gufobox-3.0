<template>
  <header class="topbar">

    <!-- ⚙️ Impostazioni -->
    <button class="tb-btn tb-btn--dark" @click="handleAdminClick" :title="adminUnlocked ? 'Chiudi Impostazioni' : 'Impostazioni'">
      ⚙️
    </button>

    <!-- 🦉 Logo -->
    <div class="tb-logo" @click="goHome">
      <div class="tb-logo__owl">🦉</div>
      <span class="tb-logo__text">GufoBox</span>
    </div>

    <!-- Pulsanti destra -->
    <div class="tb-actions">

      <!-- 🗣️ Conversazione AI -->
      <button
        class="tb-btn tb-btn--blue"
        :class="{ 'tb-btn--active': showAiChat }"
        @click="showAiChat = !showAiChat"
        title="Conversazione AI"
      >
        🗣️
      </button>

      <!-- 💡 LED On/Off -->
      <button
        class="tb-btn tb-btn--led"
        :class="{ 'tb-btn--led-off': !ledsOn }"
        @click="toggleLed"
        :title="ledsOn ? 'Spegni LED' : 'Accendi LED'"
      >
        💡
      </button>

      <!-- 🌙 Modalità Notte -->
      <button
        class="tb-btn tb-btn--moon"
        :class="{ 'tb-btn--night-active': nightMode }"
        @click="toggleNightMode"
        title="Modalità Notte"
      >
        🌙
      </button>

      <!-- 🔋 Batteria -->
      <div
        class="tb-battery"
        :class="batteryClass"
        :title="`Batteria: ${batteryPercent != null ? batteryPercent + '%' : 'N/D'}`"
      >
        {{ batteryIcon }}<span class="tb-battery__pct">{{ batteryPercent != null ? batteryPercent + '%' : '—%' }}</span>
      </div>

    </div>

  </header>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../composables/useApi'
import { useAuth } from '../composables/useAuth'

const { offline, batteryPercent, guardedCall, getApi } = useApi()
const { adminUnlocked, showAiChat, goAdmin } = useAuth()

// ── Stato LED ──────────────────────────────────────────────────────────────
const ledsOn = ref(true)

async function toggleLed() {
  try {
    const api = getApi()
    if (ledsOn.value) {
      await guardedCall(() => api.post('/led/master', {
        enabled: false,
        override_active: true,
        settings: { enabled: false, effect_id: 'off' }
      }))
      ledsOn.value = false
    } else {
      await guardedCall(() => api.post('/led/master', {
        enabled: true,
        override_active: false,
        settings: { enabled: true, effect_id: 'solid' }
      }))
      ledsOn.value = true
    }
  } catch (_) {}
}

// ── Modalità Notte ─────────────────────────────────────────────────────────
const nightMode = ref(false)

async function toggleNightMode() {
  try {
    const api = getApi()
    nightMode.value = !nightMode.value
    await guardedCall(() => api.post('/system/night_mode', { enabled: nightMode.value }))
  } catch (_) {
    nightMode.value = !nightMode.value // rollback on error
  }
}

// ── Batteria ───────────────────────────────────────────────────────────────
const batteryIcon = computed(() => {
  const p = batteryPercent.value
  if (p == null) return '🔋'
  if (p > 60) return '🔋'
  if (p > 20) return '🪫'
  return '🪫'
})

const batteryClass = computed(() => {
  const p = batteryPercent.value
  if (p != null && p <= 20) return 'battery-low'
  return ''
})

// ── Navigazione ────────────────────────────────────────────────────────────
const emit = defineEmits(['go-home'])

function goHome() {
  emit('go-home')
}

function handleAdminClick() {
  goAdmin(offline.value)
}
</script>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(13, 13, 43, 0.85);
  backdrop-filter: blur(12px);
  padding: 10px 16px;
  height: 64px;
  box-shadow: 0 2px 16px rgba(0,0,0,0.4);
  position: sticky;
  top: 0;
  z-index: 100;
  gap: 10px;
}

/* ── Logo ─────────────────────────────────────────────────── */
.tb-logo {
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  flex: 0 0 auto;
  line-height: 1;
}

.tb-logo__owl {
  font-size: 2rem;
  line-height: 1;
}

.tb-logo__text {
  font-size: 0.75rem;
  font-weight: 800;
  color: #fff;
  letter-spacing: 0.5px;
  margin-top: 1px;
}

/* ── Pulsanti generici ────────────────────────────────────── */
.tb-btn {
  background: rgba(255,255,255,0.08);
  border: none;
  border-radius: 50%;
  width: 52px;
  height: 52px;
  font-size: 1.6rem;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.2s, transform 0.15s;
  flex-shrink: 0;
}

.tb-btn:hover {
  background: rgba(255,255,255,0.18);
  transform: scale(1.08);
}

.tb-btn--dark {
  background: rgba(30,30,50,0.7);
  border: 1px solid rgba(255,255,255,0.12);
}

.tb-btn--blue {
  background: rgba(63,81,181,0.3);
  border: 1px solid rgba(63,81,181,0.5);
}

.tb-btn--blue.tb-btn--active {
  background: rgba(63,81,181,0.8);
  box-shadow: 0 0 10px rgba(63,81,181,0.6);
}

.tb-btn--led {
  background: rgba(255,200,0,0.15);
  border: 1.5px solid rgba(255,200,0,0.5);
}

.tb-btn--led-off {
  background: rgba(60,60,80,0.4);
  border-color: rgba(150,150,170,0.3);
  filter: grayscale(80%);
}

.tb-btn--moon {
  background: rgba(255,180,0,0.12);
  border: 1.5px solid rgba(255,180,0,0.35);
}

.tb-btn--night-active {
  background: rgba(255,136,51,0.35);
  border-color: #ff8833;
  box-shadow: 0 0 12px rgba(255,136,51,0.5);
}

/* ── Azioni destra ────────────────────────────────────────── */
.tb-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── Batteria ─────────────────────────────────────────────── */
.tb-battery {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 1rem;
  color: rgba(255,255,255,0.75);
  white-space: nowrap;
}

.tb-battery__pct {
  font-size: 0.72rem;
  font-weight: 600;
}

.battery-low {
  color: #ff8a80;
  animation: blink-battery 1.5s infinite;
}

@keyframes blink-battery {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@media (max-width: 400px) {
  .topbar { padding: 8px 10px; }
  .tb-btn { width: 44px; height: 44px; font-size: 1.3rem; }
  .tb-logo__text { display: none; }
}
</style>

