<template>
  <div id="app" class="gufobox-app">
    
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
import { onMounted, onBeforeUnmount } from 'vue'

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

const { selectApiBase, connectSocket, disconnectSocket, apiReady, offline } = useApi()
const { restoreSession, showAdmin } = useAuth()
const { updateAiRuntime } = useAi()
const { loadMediaStatus } = useMedia()

onMounted(async () => {
  // 1. Cerca l'IP del GufoBox sulla rete
  const found = await selectApiBase()
  
  if (found) {
    // 2. Controlla se il genitore aveva già inserito il PIN in precedenza
    await restoreSession()

    // 3. Connette il Socket.io per ricevere dati in tempo reale dal Python
    connectSocket({
      onConnect: () => {
        console.log('🔗 Connesso al GufoBox!')
        loadMediaStatus() // Forza un aggiornamento appena connesso
      },
      onPublicSnapshot: (data) => {
        // Quando il Python manda aggiornamenti, aggiorniamo il Gufetto!
        if (data?.ai_runtime) {
          updateAiRuntime(data.ai_runtime)
        }
      }
    })
  }
})

onBeforeUnmount(() => {
  disconnectSocket()
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
  background-color: var(--bg-color);
  color: var(--text-main);
  font-family: var(--font-family);
  -webkit-font-smoothing: antialiased;
}

.gufobox-app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.main-content {
  flex: 1;
  position: relative;
  overflow-x: hidden;
}

.global-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: calc(100vh - 74px);
  font-size: 1.2rem;
  color: var(--accent);
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

