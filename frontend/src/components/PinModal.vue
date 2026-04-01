<template>
  <div v-if="showPinModal" class="modal-overlay" @click.self="closePinModal">
    <div class="pin-modal">
      
      <div class="modal-header">
        <h2>Area Genitori 🔒</h2>
        <button class="btn-close" @click="closePinModal">✖</button>
      </div>

      <div class="pin-display">
        <span v-if="pinInput.length === 0" class="pin-placeholder">Inserisci il PIN</span>
        <span v-else class="pin-masked">{{ maskedPin }}</span>
      </div>

      <div v-if="pinError" class="pin-error">
        ⚠️ {{ pinError }}
      </div>
      <div v-if="pinLockedRetry > 0" class="pin-locked">
        ⏳ Troppi tentativi. Riprova tra {{ pinLockedRetry }} secondi.
      </div>

      <div class="keypad" :class="{ 'disabled-keypad': pinLockedRetry > 0 || pinBusy }">
        <button v-for="n in 9" :key="n" class="key" @click="addDigit(n)">
          {{ n }}
        </button>
        <button class="key action-key" @click="clearPin">C</button>
        <button class="key" @click="addDigit(0)">0</button>
        <button class="key action-key" @click="backspaceDigit">⌫</button>
      </div>

      <button 
        class="btn-submit" 
        :disabled="pinInput.length < 4 || pinBusy || pinLockedRetry > 0"
        @click="() => submitPin()"
      >
        <span v-if="pinBusy">Verifica... ⏳</span>
        <span v-else>Sblocca GufoBox 🔓</span>
      </button>

    </div>
  </div>
</template>

<script setup>
import { useAuth } from '../composables/useAuth'

// Importiamo tutte le variabili e funzioni necessarie dal nostro composable
const {
  showPinModal,
  pinInput,
  pinBusy,
  pinError,
  pinLockedRetry,
  maskedPin,
  closePinModal,
  addDigit,
  clearPin,
  backspaceDigit,
  submitPin
} = useAuth()
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(5px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.pin-modal {
  background: var(--surface, #2a2a35);
  border-radius: 20px;
  padding: 25px;
  width: 90%;
  max-width: 380px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h2 {
  margin: 0;
  font-size: 1.5rem;
  color: #fff;
}

.btn-close {
  background: transparent;
  border: none;
  color: #aaa;
  font-size: 1.5rem;
  cursor: pointer;
  transition: color 0.2s;
}

.btn-close:hover {
  color: #fff;
}

.pin-display {
  background: #1e1e26;
  border-radius: 12px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  letter-spacing: 5px;
  box-shadow: inset 0 2px 5px rgba(0,0,0,0.3);
}

.pin-placeholder {
  font-size: 1.2rem;
  color: #666;
  letter-spacing: normal;
}

.pin-masked {
  color: #4caf50;
}

.pin-error {
  color: #ff4d4d;
  font-size: 0.9rem;
  text-align: center;
  font-weight: bold;
}

.pin-locked {
  color: #ffd27b;
  font-size: 0.9rem;
  text-align: center;
  font-weight: bold;
}

.keypad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.disabled-keypad {
  opacity: 0.5;
  pointer-events: none;
}

.key {
  background: #3a3a48;
  border: none;
  border-radius: 12px;
  height: 60px;
  font-size: 1.8rem;
  color: #fff;
  cursor: pointer;
  transition: all 0.1s;
  box-shadow: 0 4px 0 #1e1e26;
}

.key:active {
  transform: translateY(4px);
  box-shadow: 0 0 0 #1e1e26;
}

.action-key {
  background: #4a4a5a;
  font-size: 1.5rem;
}

.btn-submit {
  background: #3f51b5;
  color: white;
  border: none;
  border-radius: 12px;
  padding: 15px;
  font-size: 1.2rem;
  font-weight: bold;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-submit:disabled {
  background: #555;
  color: #888;
  cursor: not-allowed;
}

.btn-submit:not(:disabled):hover {
  background: #5c6bc0;
}
</style>

