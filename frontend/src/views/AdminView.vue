<template>
  <div class="admin-layout">

    <aside class="admin-sidebar">
      <div class="sidebar-header">
        <span class="logo-icon">🦉</span>
        <h2>GufoBox</h2>
      </div>

      <nav class="sidebar-nav">
        <button @click="currentTab = 'dashboard'" :class="{ active: currentTab === 'dashboard' }">
          <span class="nav-icon">🏠</span>
          <span class="nav-label">Dashboard</span>
        </button>

        <button @click="currentTab = 'media-statuine'" :class="{ active: currentTab === 'media-statuine' }">
          <span class="nav-icon">🎵</span>
          <span class="nav-label">Media &amp; Statuine</span>
        </button>

        <button @click="currentTab = 'files'" :class="{ active: currentTab === 'files' }">
          <span class="nav-icon">📁</span>
          <span class="nav-label">File</span>
        </button>

        <button @click="currentTab = 'voice'" :class="{ active: currentTab === 'voice' }">
          <span class="nav-icon">🎙️</span>
          <span class="nav-label">Voce</span>
        </button>

        <button @click="currentTab = 'offline-voice'" :class="{ active: currentTab === 'offline-voice' }">
          <span class="nav-icon">📴</span>
          <span class="nav-label">Voce offline</span>
        </button>

        <button @click="currentTab = 'parental'" :class="{ active: currentTab === 'parental' }">
          <span class="nav-icon">🛡️</span>
          <span class="nav-label">Parental</span>
        </button>

        <button @click="currentTab = 'stats'" :class="{ active: currentTab === 'stats' }">
          <span class="nav-icon">📊</span>
          <span class="nav-label">Statistiche</span>
        </button>

        <button @click="currentTab = 'ai'" :class="{ active: currentTab === 'ai' }">
          <span class="nav-icon">🧠</span>
          <span class="nav-label">Gufetto</span>
        </button>

        <button @click="currentTab = 'led'" :class="{ active: currentTab === 'led' }">
          <span class="nav-icon">💡</span>
          <span class="nav-label">LED</span>
        </button>

        <button @click="currentTab = 'network'" :class="{ active: currentTab === 'network' }">
          <span class="nav-icon">📶</span>
          <span class="nav-label">Rete</span>
        </button>

        <button @click="currentTab = 'bluetooth'" :class="{ active: currentTab === 'bluetooth' }">
          <span class="nav-icon">🛜</span>
          <span class="nav-label">Bluetooth</span>
        </button>

        <button @click="currentTab = 'audio'" :class="{ active: currentTab === 'audio' }">
          <span class="nav-icon">🔊</span>
          <span class="nav-label">Audio</span>
        </button>

        <button @click="currentTab = 'alarm'" :class="{ active: currentTab === 'alarm' }">
          <span class="nav-icon">⏰</span>
          <span class="nav-label">Sveglia</span>
        </button>

        <button @click="currentTab = 'datetime'" :class="{ active: currentTab === 'datetime' }">
          <span class="nav-icon">🕐</span>
          <span class="nav-label">Data/Ora</span>
        </button>

        <button @click="currentTab = 'system'" :class="{ active: currentTab === 'system' }">
          <span class="nav-icon">⚙️</span>
          <span class="nav-label">Sistema</span>
        </button>

        <button @click="currentTab = 'diag'" :class="{ active: currentTab === 'diag' }">
          <span class="nav-icon">🔬</span>
          <span class="nav-label">Diagnostica</span>
        </button>

        <button @click="currentTab = 'gpio'" :class="{ active: currentTab === 'gpio' }">
          <span class="nav-icon">📌</span>
          <span class="nav-label">GPIO Pinout</span>
        </button>
      </nav>

      <div class="sidebar-footer">
        <button class="btn-logout" @click="handleLogout" :disabled="loggingOut">
          {{ loggingOut ? '⏳ Uscita...' : '🚪 Esci' }}
        </button>
      </div>
    </aside>

    <main class="admin-content">
      <!-- Offline banner -->
      <div v-if="offline" class="offline-bar">
        ⚠️ Connessione al backend persa — alcune funzioni potrebbero non essere disponibili
      </div>

      <transition name="fade" mode="out-in">
        <div :key="currentTab" class="tab-container">

          <AdminDashboard v-if="currentTab === 'dashboard'" />

          <AdminMediaStatuine v-if="currentTab === 'media-statuine'" />

          <AdminFileManager v-if="currentTab === 'files'" />

          <AdminVoiceRecord v-if="currentTab === 'voice'" />

          <AdminOfflineVoice v-if="currentTab === 'offline-voice'" />

          <AdminParental v-if="currentTab === 'parental'" />

          <AdminStats v-if="currentTab === 'stats'" />

          <AdminAiSettings v-if="currentTab === 'ai'" />

          <AdminLed v-if="currentTab === 'led'" />

          <AdminNetwork v-if="currentTab === 'network'" />

          <AdminBluetooth v-if="currentTab === 'bluetooth'" />

          <AdminAudio v-if="currentTab === 'audio'" />

          <AdminAlarm v-if="currentTab === 'alarm'" />

          <AdminDateTime v-if="currentTab === 'datetime'" />

          <AdminSystem v-if="currentTab === 'system'" />

          <AdminDiagnostics v-if="currentTab === 'diag'" />

          <AdminGpioPinout v-if="currentTab === 'gpio'" />

        </div>
      </transition>
    </main>

  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useAuth } from '../composables/useAuth'
import { useApi } from '../composables/useApi'

import AdminDashboard from './admin/AdminDashboard.vue'
import AdminMediaStatuine from './admin/AdminMediaStatuine.vue'
import AdminFileManager from './admin/AdminFileManager.vue'
import AdminVoiceRecord from './admin/AdminVoiceRecord.vue'
import AdminOfflineVoice from './admin/AdminOfflineVoice.vue'
import AdminParental from './admin/AdminParental.vue'
import AdminStats from './admin/AdminStats.vue'
import AdminAiSettings from './admin/AdminAiSettings.vue'
import AdminNetwork from './admin/AdminNetwork.vue'
import AdminBluetooth from './admin/AdminBluetooth.vue'
import AdminAudio from './admin/AdminAudio.vue'
import AdminLed from './admin/AdminLed.vue'
import AdminAlarm from './admin/AdminAlarm.vue'
import AdminDateTime from './admin/AdminDateTime.vue'
import AdminSystem from './admin/AdminSystem.vue'
import AdminDiagnostics from './admin/AdminDiagnostics.vue'
import AdminGpioPinout from './admin/AdminGpioPinout.vue'

const { logoutAdmin } = useAuth()
const { offline } = useApi()

const currentTab = ref('dashboard')
const loggingOut = ref(false)

async function handleLogout() {
  if (loggingOut.value) return
  loggingOut.value = true
  try {
    await logoutAdmin()
  } finally {
    loggingOut.value = false
  }
}
</script>

<style scoped>
/* -------------------------------------------
   LAYOUT PRINCIPALE 
------------------------------------------- */
.admin-layout {
  display: flex;
  height: 100vh;
  background-color: #121218;
  color: #ffffff;
  overflow: hidden;
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

/* -------------------------------------------
   BARRA LATERALE (DESKTOP)
------------------------------------------- */
.admin-sidebar {
  width: 250px;
  background-color: #1c1c24;
  border-right: 1px solid #2d2d3a;
  display: flex;
  flex-direction: column;
  z-index: 10;
}

.sidebar-header {
  padding: 25px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid #2d2d3a;
}

.logo-icon {
  font-size: 2rem;
}

.sidebar-header h2 {
  font-size: 1.5rem;
  color: #ffd27b;
  margin: 0;
  font-weight: 700;
}

.sidebar-nav {
  flex: 1;
  padding: 15px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}

.sidebar-nav button {
  display: flex;
  align-items: center;
  gap: 15px;
  background: transparent;
  border: none;
  color: #a0a0b0;
  padding: 12px 15px;
  border-radius: 12px;
  cursor: pointer;
  font-size: 1.05rem;
  transition: all 0.2s ease;
  text-align: left;
}

.sidebar-nav button:hover {
  background-color: #2a2a35;
  color: #ffffff;
}

.sidebar-nav button.active {
  background-color: #3f51b5;
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(63, 81, 181, 0.4);
  font-weight: bold;
}

.nav-icon {
  font-size: 1.2rem;
}

.sidebar-footer {
  padding: 20px;
  border-top: 1px solid #2d2d3a;
}

.btn-logout {
  width: 100%;
  background: rgba(255, 77, 77, 0.1);
  color: #ff4d4d;
  border: 1px solid rgba(255, 77, 77, 0.3);
  padding: 12px;
  border-radius: 10px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-logout:hover {
  background: #ff4d4d;
  color: #fff;
}

/* -------------------------------------------
   AREA CONTENUTI PRINCIPALE
------------------------------------------- */
.admin-content {
  flex: 1;
  padding: 30px;
  overflow-y: auto;
  background: radial-gradient(circle at top right, #1e1e2e, #121218);
}

.tab-container {
  max-width: 1000px;
  margin: 0 auto;
  padding-bottom: 40px;
}

.placeholder-card {
  background: #1c1c24;
  padding: 40px;
  border-radius: 16px;
  text-align: center;
  border: 1px solid #2d2d3a;
  margin-top: 20px;
}

/* Offline notification bar */
.offline-bar {
  background: #2a1a1a;
  border-bottom: 1px solid #ff4d4d;
  color: #ff8a80;
  padding: 8px 20px;
  font-size: 0.9rem;
  text-align: center;
}

/* -------------------------------------------
   ANIMAZIONI (TRANSIZIONI VUE)
------------------------------------------- */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* -------------------------------------------
   RESPONSIVE MOBILE (STILE APP PWA)
------------------------------------------- */
@media (max-width: 768px) {
  .admin-layout {
    flex-direction: column;
  }

  /* La barra laterale diventa una barra inferiore fissa */
  .admin-sidebar {
    width: 100%;
    height: 70px; /* Altezza della barra in basso */
    order: 2; /* Sposta il menu sotto ai contenuti */
    border-right: none;
    border-top: 1px solid #2d2d3a;
    background-color: #1c1c24;
    position: fixed;
    bottom: 0;
    left: 0;
    z-index: 100;
  }

  .sidebar-header,
  .sidebar-footer {
    display: none; /* Nascondiamo logo e tasto esci su mobile per fare spazio */
  }

  .sidebar-nav {
    flex-direction: row;
    justify-content: space-around;
    align-items: center;
    padding: 5px;
    overflow-x: auto; /* Permette lo scorrimento orizzontale se ci sono troppi bottoni */
  }

  .sidebar-nav button {
    flex-direction: column;
    gap: 4px;
    padding: 8px;
    border-radius: 8px;
    font-size: 0.75rem;
    min-width: 65px;
    text-align: center;
  }

  .sidebar-nav button.active {
    background-color: transparent;
    color: #ffd27b;
    box-shadow: none;
  }

  .sidebar-nav button.active .nav-icon {
    transform: scale(1.2);
    color: #ffd27b;
  }

  .nav-icon {
    font-size: 1.4rem;
    transition: transform 0.2s;
  }

  .nav-label {
    display: block;
    white-space: nowrap;
  }

  /* I contenuti si adattano per non finire sotto la barra */
  .admin-content {
    order: 1;
    padding: 20px;
    padding-bottom: 90px; /* Spazio extra per non coprire l'ultimo elemento con la barra */
  }
}
</style>

