<template>
  <header class="topbar">
    
    <div class="top-left" @click="goHome">
      <div class="logo-box">🦉</div>
      <h1 class="brand">GufoBox</h1>
    </div>

    <div class="top-right">
      
      <div v-if="offline" class="top-icon text-red" title="Dispositivo Offline">
        ⚠️ Offline
      </div>

      <div class="top-icon battery-icon" title="Batteria">
        🔋 100%
      </div>

      <button 
        class="btn-admin-toggle" 
        @click="handleAdminClick"
        :title="adminUnlocked ? 'Chiudi Impostazioni' : 'Sblocca Impostazioni'"
      >
        {{ adminUnlocked ? '⚙️' : '🔒' }}
      </button>

    </div>
  </header>
</template>

<script setup>
import { useApi } from '../composables/useApi'
import { useAuth } from '../composables/useAuth'

// Importiamo lo stato della rete e dell'autenticazione
const { offline } = useApi()
const { adminUnlocked, goAdmin } = useAuth()

// Definiamo un evento ("emit") nel caso volessimo far sapere 
// al componente padre (App.vue) che l'utente vuole tornare alla Home
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
  justify-content: space-between;
  align-items: center;
  background: var(--surface, #2a2a35);
  padding: 10px 20px;
  height: 74px;
  box-shadow: 0 4px 15px rgba(0,0,0,0.3);
  position: sticky;
  top: 0;
  z-index: 100;
}

.top-left {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
}

.logo-box {
  font-size: 2rem;
  background: #3f51b5;
  border-radius: 12px;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 10px rgba(0,0,0,0.2);
}

.brand {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 800;
  color: #fff;
  letter-spacing: 1px;
}

.top-right {
  display: flex;
  align-items: center;
  gap: 15px;
}

.top-icon {
  font-size: 1.1rem;
  display: flex;
  align-items: center;
  gap: 5px;
  font-weight: 600;
}

.text-red {
  color: #ff4d4d;
}

.btn-admin-toggle {
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 50%;
  width: 44px;
  height: 44px;
  font-size: 1.3rem;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-admin-toggle:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: scale(1.05);
}

@media (max-width: 860px) {
  .topbar {
    padding: 10px;
  }
  .brand {
    font-size: 1.35rem;
  }
  .top-right {
    gap: 10px;
  }
}
</style>

