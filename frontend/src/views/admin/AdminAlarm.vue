<template>
  <div class="admin-alarm">

    <div class="header-section">
      <h2>Sveglia ⏰</h2>
      <p>Configura le sveglie con orario e giorni della settimana.</p>
    </div>

    <!-- Feedback banner -->
    <div v-if="feedbackMsg" class="banner" :class="'banner-' + feedbackType">
      <span>{{ feedbackMsg }}</span>
      <button class="banner-close" @click="clearFeedback">✕</button>
    </div>

    <!-- Aggiungi / Modifica sveglia -->
    <div class="card">
      <h3>{{ editingId ? '✏️ Modifica Sveglia' : '➕ Nuova Sveglia' }}</h3>

      <div class="alarm-form">
        <div class="form-row">
          <div class="form-group">
            <label>Orario</label>
            <div class="time-inputs">
              <input
                type="number" min="0" max="23"
                v-model.number="form.hour"
                class="input-time"
                placeholder="HH"
              />
              <span class="time-sep">:</span>
              <input
                type="number" min="0" max="59"
                v-model.number="form.minute"
                class="input-time"
                placeholder="MM"
              />
            </div>
          </div>

          <div class="form-group">
            <label>Etichetta</label>
            <input
              type="text"
              v-model="form.label"
              class="input-text"
              placeholder="Sveglia 🦉"
              maxlength="40"
            />
          </div>
        </div>

        <!-- Giorni della settimana -->
        <div class="form-group">
          <label>Giorni della settimana</label>
          <div class="days-selector">
            <button
              v-for="(dayLabel, idx) in dayNames"
              :key="idx"
              class="day-btn"
              :class="{ 'day-btn--active': form.days.includes(idx) }"
              @click="toggleDay(idx)"
              type="button"
            >
              {{ dayLabel }}
            </button>
          </div>
        </div>

        <!-- Target audio (opzionale) -->
        <div class="form-group">
          <label>Audio (percorso file o URL radio — opzionale)</label>
          <input
            type="text"
            v-model="form.target"
            class="input-text"
            placeholder="/home/gufobox/media/contenuti/... oppure http://stream..."
          />
        </div>

        <!-- Enable toggle -->
        <div class="form-group form-group--inline">
          <label class="toggle-label">
            <input type="checkbox" v-model="form.enabled" />
            Sveglia abilitata
          </label>
        </div>

        <div class="form-actions">
          <button class="btn-primary" @click="saveAlarm" :disabled="busy">
            {{ busy ? '⏳ Salvataggio...' : (editingId ? '💾 Aggiorna' : '➕ Aggiungi') }}
          </button>
          <button v-if="editingId" class="btn-secondary" @click="cancelEdit">
            Annulla
          </button>
        </div>
      </div>
    </div>

    <!-- Lista sveglie -->
    <div class="card">
      <div class="card-header">
        <h3>Sveglie Configurate</h3>
        <button class="btn-refresh" @click="loadAlarms" title="Aggiorna lista">🔄</button>
      </div>

      <div v-if="loading" class="empty-state">⏳ Caricamento...</div>

      <div v-else-if="alarms.length === 0" class="empty-state">
        Nessuna sveglia configurata. Aggiungine una qui sopra!
      </div>

      <div v-else class="alarms-list">
        <div
          v-for="alarm in alarms"
          :key="alarm.id"
          class="alarm-item"
          :class="{ 'alarm-item--disabled': !alarm.enabled }"
        >
          <div class="alarm-main">
            <div class="alarm-time">
              {{ padTwo(alarm.hour) }}:{{ padTwo(alarm.minute) }}
            </div>
            <div class="alarm-details">
              <span class="alarm-label">{{ alarm.label || 'Sveglia' }}</span>
              <span class="alarm-days">{{ formatDays(alarm.days) }}</span>
              <span v-if="alarm.target" class="alarm-target" :title="alarm.target">
                🎵 {{ truncate(alarm.target, 40) }}
              </span>
            </div>
          </div>

          <div class="alarm-controls">
            <button
              class="btn-toggle"
              @click="toggleEnabled(alarm)"
              :title="alarm.enabled ? 'Disabilita' : 'Abilita'"
            >
              {{ alarm.enabled ? '✅' : '⭕' }}
            </button>
            <button class="btn-icon" @click="startEdit(alarm)" title="Modifica">✏️</button>
            <button class="btn-icon btn-icon--danger" @click="deleteAlarm(alarm.id)" title="Elimina">🗑️</button>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAdminFeedback } from '../../composables/useAdminFeedback'

const { getApi, guardedCall, extractApiError } = useApi()
const { feedbackMsg, feedbackType, showSuccess, showError, clearFeedback } = useAdminFeedback()

const dayNames = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']

const alarms = ref([])
const loading = ref(false)
const busy = ref(false)
const editingId = ref(null)

const form = reactive({
  hour: 8,
  minute: 0,
  label: 'Sveglia 🦉',
  days: [0, 1, 2, 3, 4, 5, 6],
  target: '',
  enabled: true,
})

function resetForm() {
  form.hour = 8
  form.minute = 0
  form.label = 'Sveglia 🦉'
  form.days = [0, 1, 2, 3, 4, 5, 6]
  form.target = ''
  form.enabled = true
  editingId.value = null
}

function toggleDay(idx) {
  const i = form.days.indexOf(idx)
  if (i >= 0) {
    form.days.splice(i, 1)
  } else {
    form.days.push(idx)
    form.days.sort((a, b) => a - b)
  }
}

function padTwo(n) {
  return String(n).padStart(2, '0')
}

function formatDays(days) {
  if (!days || days.length === 0) return 'Nessun giorno'
  if (days.length === 7) return 'Ogni giorno'
  if (JSON.stringify([...days].sort()) === JSON.stringify([0, 1, 2, 3, 4])) return 'Lun–Ven'
  if (JSON.stringify([...days].sort()) === JSON.stringify([5, 6])) return 'Sab–Dom'
  return days.map(d => dayNames[d]).join(', ')
}

function truncate(str, max) {
  if (!str) return ''
  return str.length > max ? str.slice(0, max) + '…' : str
}

async function loadAlarms() {
  loading.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/alarms'))
    alarms.value = Array.isArray(data) ? data : []
  } catch (e) {
    showError(extractApiError(e, 'Errore caricamento sveglie'))
  } finally {
    loading.value = false
  }
}

async function saveAlarm() {
  if (form.days.length === 0) {
    showError('Seleziona almeno un giorno della settimana.')
    return
  }
  busy.value = true
  clearFeedback()
  try {
    const api = getApi()
    const payload = {
      hour: form.hour,
      minute: form.minute,
      label: form.label || 'Sveglia 🦉',
      days: [...form.days],
      target: form.target || '',
      enabled: form.enabled,
    }
    if (editingId.value) {
      await guardedCall(() => api.put(`/alarms/${editingId.value}`, payload))
      showSuccess('Sveglia aggiornata ✅')
    } else {
      await guardedCall(() => api.post('/alarms', payload))
      showSuccess('Sveglia aggiunta ✅')
    }
    resetForm()
    await loadAlarms()
  } catch (e) {
    showError(extractApiError(e, 'Errore salvataggio sveglia'))
  } finally {
    busy.value = false
  }
}

function startEdit(alarm) {
  editingId.value = alarm.id
  form.hour = alarm.hour
  form.minute = alarm.minute
  form.label = alarm.label || 'Sveglia 🦉'
  form.days = [...(alarm.days || [])]
  form.target = alarm.target || ''
  form.enabled = alarm.enabled !== false
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function cancelEdit() {
  resetForm()
}

async function toggleEnabled(alarm) {
  try {
    const api = getApi()
    await guardedCall(() => api.put(`/alarms/${alarm.id}`, { enabled: !alarm.enabled }))
    alarm.enabled = !alarm.enabled
  } catch (e) {
    showError(extractApiError(e, 'Errore aggiornamento sveglia'))
  }
}

async function deleteAlarm(id) {
  if (!confirm('Eliminare questa sveglia?')) return
  try {
    const api = getApi()
    await guardedCall(() => api.delete(`/alarms/${id}`))
    alarms.value = alarms.value.filter(a => a.id !== id)
    showSuccess('Sveglia eliminata')
  } catch (e) {
    showError(extractApiError(e, 'Errore eliminazione sveglia'))
  }
}

onMounted(() => loadAlarms())
</script>

<style scoped>
.admin-alarm { max-width: 700px; }

.header-section { margin-bottom: 24px; }
.header-section h2 { font-size: 1.6rem; font-weight: 700; color: #ffd27b; margin: 0 0 6px; }
.header-section p { color: #aaa; margin: 0; }

.card {
  background: #1e1e2e;
  border: 1px solid #2d2d3d;
  border-radius: 14px;
  padding: 22px;
  margin-bottom: 20px;
}
.card h3 { font-size: 1.1rem; font-weight: 700; color: #fff; margin: 0 0 16px; }

.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.card-header h3 { margin: 0; }

.banner {
  padding: 12px 16px; border-radius: 10px; display: flex;
  justify-content: space-between; align-items: center; margin-bottom: 16px; font-size: 0.95rem;
}
.banner-success { background: rgba(76,175,80,0.15); border: 1px solid #4caf50; color: #81c784; }
.banner-error   { background: rgba(244,67,54,0.15); border: 1px solid #f44336; color: #e57373; }
.banner-close { background: none; border: none; color: inherit; cursor: pointer; font-size: 1rem; }

.alarm-form { display: flex; flex-direction: column; gap: 14px; }
.form-row { display: flex; gap: 16px; flex-wrap: wrap; }
.form-group { display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 140px; }
.form-group label { font-size: 0.85rem; color: #aaa; font-weight: 600; }

.time-inputs { display: flex; align-items: center; gap: 6px; }
.input-time {
  background: #252535; border: 1px solid #3a3a50; border-radius: 8px;
  color: #fff; font-size: 1.3rem; font-weight: 700; padding: 8px 10px;
  width: 60px; text-align: center;
}
.time-sep { font-size: 1.4rem; font-weight: 700; color: #ffd27b; }

.input-text {
  background: #252535; border: 1px solid #3a3a50; border-radius: 8px;
  color: #fff; font-size: 0.95rem; padding: 9px 12px; width: 100%;
}
.input-text:focus, .input-time:focus { outline: none; border-color: #3f51b5; }

.days-selector { display: flex; gap: 6px; flex-wrap: wrap; }
.day-btn {
  background: #252535; border: 1.5px solid #3a3a50; border-radius: 20px;
  color: #aaa; font-size: 0.82rem; font-weight: 700; padding: 5px 11px; cursor: pointer; transition: all 0.18s;
}
.day-btn:hover { border-color: #5c6bc0; color: #fff; }
.day-btn--active { background: #3f51b5; border-color: #3f51b5; color: #fff; box-shadow: 0 0 8px rgba(63,81,181,0.4); }

.form-group--inline { flex-direction: row; align-items: center; }
.toggle-label { display: flex; align-items: center; gap: 10px; cursor: pointer; font-size: 0.9rem; color: #ddd; }
.toggle-label input[type=checkbox] { width: 18px; height: 18px; cursor: pointer; accent-color: #3f51b5; }

.form-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.btn-primary {
  background: #3f51b5; border: none; border-radius: 9px; color: #fff;
  font-size: 0.95rem; font-weight: 700; padding: 10px 22px; cursor: pointer; transition: background 0.2s;
}
.btn-primary:hover:not(:disabled) { background: #5c6bc0; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
  border-radius: 9px; color: #aaa; font-size: 0.95rem; padding: 10px 20px; cursor: pointer;
}
.btn-secondary:hover { background: rgba(255,255,255,0.15); color: #fff; }

.btn-refresh {
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12);
  border-radius: 8px; color: #ccc; font-size: 1rem; padding: 6px 12px; cursor: pointer;
}
.btn-refresh:hover { background: rgba(255,255,255,0.16); }

.empty-state { color: #666; text-align: center; padding: 24px; font-size: 0.95rem; }

.alarms-list { display: flex; flex-direction: column; gap: 10px; }
.alarm-item {
  display: flex; align-items: center; justify-content: space-between;
  background: #252535; border: 1px solid #3a3a50; border-radius: 12px;
  padding: 14px 16px; gap: 12px; transition: opacity 0.2s;
}
.alarm-item--disabled { opacity: 0.45; }
.alarm-main { display: flex; align-items: center; gap: 16px; flex: 1; min-width: 0; }
.alarm-time { font-size: 1.6rem; font-weight: 800; color: #ffd27b; min-width: 72px; font-variant-numeric: tabular-nums; }
.alarm-details { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.alarm-label { font-weight: 700; color: #fff; font-size: 0.95rem; }
.alarm-days { font-size: 0.8rem; color: #888; }
.alarm-target { font-size: 0.75rem; color: #666; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 260px; }

.alarm-controls { display: flex; align-items: center; gap: 6px; }
.btn-toggle { background: none; border: none; font-size: 1.3rem; cursor: pointer; padding: 4px; line-height: 1; transition: transform 0.15s; }
.btn-toggle:hover { transform: scale(1.15); }
.btn-icon {
  background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 7px; font-size: 1rem; padding: 6px 8px; cursor: pointer; color: #ddd; transition: background 0.18s;
}
.btn-icon:hover { background: rgba(255,255,255,0.15); }
.btn-icon--danger { border-color: rgba(244,67,54,0.3); color: #e57373; }
.btn-icon--danger:hover { background: rgba(244,67,54,0.2); border-color: #f44336; }

@media (max-width: 480px) {
  .alarm-time { font-size: 1.3rem; min-width: 58px; }
  .form-row { flex-direction: column; }
}
</style>
