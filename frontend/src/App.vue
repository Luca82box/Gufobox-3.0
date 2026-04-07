<template>
  <div id="app" class="gufobox-app">
    
    <!-- Sfondo animato stelle/comete -->
    <canvas ref="bgCanvas" class="bg-canvas" aria-hidden="true"></canvas>

    <TopBar @go-home="showAdmin = false" />

    <div v-if="!apiReady && !offline" class="global-loading">
      <div class="spinner">🦉</div>
      <p>Ricerca GufoBox in corso...</p>
    </div>

    <main v-else-if="apiReady || offline" class="main-content">
      
      <HomeView v-if="!showAdmin" />
      
      <AdminView v-else />
      
    </main>

    <PinModal />

  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'

// Importiamo i Componenti Visivi
import TopBar from './components/TopBar.vue'
import PinModal from './components/PinModal.vue'
import HomeView from './views/HomeView.vue'
import AdminView from './views/AdminView.vue'

// Importiamo la logica globale
import { useApi } from './composables/useApi'
import { useAuth } from './composables/useAuth'
import { useAi } from './composables/useAi'
import { useMedia } from './composables/useMedia'

const { selectApiBase, connectSocket, disconnectSocket, apiReady, offline, batteryPercent } = useApi()
const { restoreSession, showAdmin, adminUnlocked, logoutAdmin } = useAuth()

const { updateAiRuntime } = useAi()
const { loadMediaStatus } = useMedia()

// ─── Canvas sfondo stelle/comete ────────────────────────────────────────────
const bgCanvas = ref(null)
let _bgAnimId = null

function initStarBackground(canvas) {
  const ctx = canvas.getContext('2d')
  let W = window.innerWidth
  let H = window.innerHeight
  canvas.width = W
  canvas.height = H

  // Riduce il numero di stelle su schermi piccoli per risparmiare batteria e CPU.
  // Threshold 768px copre tutti i telefoni e i tablet in portrait.
  const isMobile = W < 768
  const NUM_STARS = isMobile ? 40 : 120
  const NUM_COMETS = isMobile ? 1 : 3

  const stars = Array.from({ length: NUM_STARS }, () => ({
    x: Math.random() * W,
    y: Math.random() * H,
    r: Math.random() * 1.5 + 0.3,
    alpha: Math.random(),
    dAlpha: (Math.random() * 0.008 + 0.002) * (Math.random() < 0.5 ? 1 : -1),
  }))

  const comets = Array.from({ length: NUM_COMETS }, () => newComet(W, H))

  function newComet(w, h) {
    return {
      x: Math.random() * w,
      y: Math.random() * h * 0.5,
      len: Math.random() * 120 + 60,
      speed: Math.random() * 4 + 2,
      alpha: Math.random() * 0.6 + 0.3,
      angle: Math.PI / 4 + (Math.random() - 0.5) * 0.3,
      life: 0,
      maxLife: Math.random() * 80 + 40,
    }
  }

  function resize() {
    W = window.innerWidth
    H = window.innerHeight
    canvas.width = W
    canvas.height = H
  }
  window.addEventListener('resize', resize)

  // Pausa l'animazione quando la scheda/app non è visibile per risparmiare
  // CPU e batteria (importante soprattutto su dispositivi mobili).
  let paused = false
  function onVisibilityChange() {
    paused = document.hidden
    if (!paused && !_bgAnimId) {
      // Riprende il loop se era stato fermato
      draw()
    }
  }
  document.addEventListener('visibilitychange', onVisibilityChange)

  function draw() {
    if (paused) {
      _bgAnimId = null
      return
    }
    ctx.clearRect(0, 0, W, H)

    // Stelle
    for (const s of stars) {
      s.alpha += s.dAlpha
      if (s.alpha <= 0 || s.alpha >= 1) s.dAlpha *= -1
      s.alpha = Math.max(0.05, Math.min(1, s.alpha))
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(255,255,255,${s.alpha})`
      ctx.fill()
    }

    // Comete
    for (let i = 0; i < comets.length; i++) {
      const c = comets[i]
      c.life++
      const progress = c.life / c.maxLife
      const cx = c.x + Math.cos(c.angle) * c.speed * c.life
      const cy = c.y + Math.sin(c.angle) * c.speed * c.life
      const tx = cx - Math.cos(c.angle) * c.len * (1 - progress)
      const ty = cy - Math.sin(c.angle) * c.len * (1 - progress)

      const grad = ctx.createLinearGradient(tx, ty, cx, cy)
      grad.addColorStop(0, `rgba(255,255,255,0)`)
      grad.addColorStop(1, `rgba(255,255,255,${c.alpha * (1 - progress)})`)
      ctx.beginPath()
      ctx.moveTo(tx, ty)
      ctx.lineTo(cx, cy)
      ctx.strokeStyle = grad
      ctx.lineWidth = 1.5
      ctx.stroke()

      if (c.life >= c.maxLife) comets[i] = newComet(W, H)
    }

    _bgAnimId = requestAnimationFrame(draw)
  }
  draw()
  return () => {
    window.removeEventListener('resize', resize)
    document.removeEventListener('visibilitychange', onVisibilityChange)
    if (_bgAnimId) cancelAnimationFrame(_bgAnimId)
    _bgAnimId = null
  }
}

// ─── Socket / lifecycle ──────────────────────────────────────────────────────

async function onReconnect() {
  loadMediaStatus()
  if (adminUnlocked.value || showAdmin.value) {
    const stillValid = await restoreSession()
    if (!stillValid && showAdmin.value) {
      await logoutAdmin()
    }
  }
}

let _bgCleanup = null

onMounted(async () => {
  // Avvia sfondo animato
  if (bgCanvas.value) {
    _bgCleanup = initStarBackground(bgCanvas.value)
  }

  // 1. Cerca l'IP del GufoBox sulla rete
  const found = await selectApiBase()

  if (found) {
    // 2. Controlla se il genitore aveva già inserito il PIN in precedenza
    await restoreSession()

    // 3. Connette il Socket.io per ricevere dati in tempo reale dal Python
    connectSocket({
      onConnect: onReconnect,
      onPublicSnapshot: (data) => {
        if (data?.ai_runtime) {
          updateAiRuntime(data.ai_runtime)
        }
        // Aggiorna percentuale batteria (clamped 0-100)
        const batt = data?.state?.battery
        if (batt && batt.percent != null) {
          batteryPercent.value = Math.max(0, Math.min(100, Math.round(batt.percent)))
        }
      },
      onAdminSnapshot: (_data) => {},
      onJobsUpdate: (_data) => {},
      onOtaUpdate: (_data) => {}
    })
  }
})

onBeforeUnmount(() => {
  disconnectSocket()
  if (_bgCleanup) _bgCleanup()
})
</script>

<style>
/* ========================================================= */
/* STILI GLOBALI (Reset e Variabili)                         */
/* ========================================================= */
:root {
  --bg-color: #121216;
  --surface: #1e1e26;
  --primary: #3f51b5;
  --primary-hover: #5c6bc0;
  --accent: #ffd27b;
  --text-main: #ffffff;
  --text-muted: #aaaaaa;
  --danger: #ff4d4d;
  --success: #4caf50;
  --font-family: 'Nunito', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  padding: 0;
  background: linear-gradient(180deg, #0d0d2b 0%, #1a0a2e 50%, #2d1b4e 100%);
  background-attachment: fixed;
  color: var(--text-main);
  font-family: var(--font-family);
  -webkit-font-smoothing: antialiased;
}

.gufobox-app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

.bg-canvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
  will-change: transform;
}

.main-content {
  flex: 1;
  position: relative;
  z-index: 1;
  overflow-x: hidden;
}

/* TopBar sopra il canvas */
header {
  position: relative;
  z-index: 2;
}

.global-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: calc(100vh - 74px);
  font-size: 1.2rem;
  color: var(--accent);
  position: relative;
  z-index: 1;
}

.spinner {
  font-size: 4rem;
  animation: bounce 1s infinite alternate;
  margin-bottom: 20px;
}

@keyframes bounce {
  from { transform: translateY(0); }
  to { transform: translateY(-20px); }
}

/* Scrollbar personalizzata per tutta l'app */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg-color); }
::-webkit-scrollbar-thumb { background: #3a3a48; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #555; }
</style>
