<template>
  <div class="admin-gpio-pinout">

    <div class="header-section">
      <h2>📌 GPIO Pinout</h2>
      <p>Mappa completa dei pin GPIO del Raspberry Pi usati da GufoBox e le periferiche corrispondenti.</p>
    </div>

    <!-- Pinout table -->
    <div class="card">
      <div class="card-header">
        <h3>Mappa Pin GPIO</h3>
        <button class="btn-refresh" @click="loadPinout" :disabled="loading">
          {{ loading ? '⏳' : '🔄' }}
        </button>
      </div>

      <div v-if="loading" class="loading-text">Caricamento... ⏳</div>

      <div v-else class="table-wrapper">
        <table class="pinout-table">
          <thead>
            <tr>
              <th>Periferica</th>
              <th>GPIO</th>
              <th>Pin Fisico</th>
              <th>Protocollo / Bus</th>
              <th>File Sorgente</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="pin in pinout" :key="pin.gpio + '-' + pin.peripheral">
              <td class="pin-peripheral">{{ pin.peripheral }}</td>
              <td class="pin-gpio">GPIO {{ pin.gpio }}</td>
              <td class="pin-physical">Pin {{ pin.physical_pin }}</td>
              <td>
                <span class="badge" :class="protocolClass(pin.protocol)">
                  {{ pin.protocol }}
                </span>
              </td>
              <td class="pin-source">{{ pin.source }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Legend -->
    <div class="card legend-card">
      <div class="card-header">
        <h3>Legenda Colori</h3>
      </div>
      <div class="legend-grid">
        <div class="legend-item">
          <span class="badge badge-gpio-input">GPIO Input</span>
          <span class="legend-desc">Ingresso digitale con pull-up (pulsanti)</span>
        </div>
        <div class="legend-item">
          <span class="badge badge-gpio-output">GPIO Output</span>
          <span class="legend-desc">Uscita digitale (amplificatore)</span>
        </div>
        <div class="legend-item">
          <span class="badge badge-pwm">PWM0</span>
          <span class="legend-desc">Segnale PWM hardware (striscia LED)</span>
        </div>
        <div class="legend-item">
          <span class="badge badge-spi">SPI0</span>
          <span class="legend-desc">Bus SPI (lettore RFID RC522)</span>
        </div>
        <div class="legend-item">
          <span class="badge badge-i2c">I2C1</span>
          <span class="legend-desc">Bus I2C (gauge batteria MAX17048)</span>
        </div>
      </div>
    </div>

    <!-- Notes -->
    <div class="card notes-card">
      <div class="card-header">
        <h3>⚠️ Note</h3>
      </div>
      <ul class="notes-list">
        <li v-for="note in notes" :key="note">{{ note }}</li>
        <li v-if="notes.length === 0">
          GPIO 3 è condiviso: funge sia da I2C1 SCL per il MAX17048,
          sia da pulsante Power/Wake (pull-up hardware 1.8kΩ).
        </li>
      </ul>
    </div>

    <!-- ASCII header diagram -->
    <div class="card ascii-card">
      <div class="card-header">
        <h3>Diagramma Header 40-Pin</h3>
      </div>
      <p class="ascii-hint">I pin usati da GufoBox sono segnati con <strong>[##]</strong>, quelli liberi con <em>(##)</em>.</p>
      <pre class="ascii-diagram">{{ asciiDiagram }}</pre>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { getApi, guardedCall, extractApiError } = useApi()

const loading = ref(false)
const notes = ref([])

// Dati statici di fallback — sempre disponibili anche senza backend
const STATIC_PINOUT = [
  { peripheral: 'Pulsante Play/Pausa',      gpio: 5,  physical_pin: 29, protocol: 'GPIO Input',  source: 'hw/buttons.py' },
  { peripheral: 'Pulsante Next',             gpio: 6,  physical_pin: 31, protocol: 'GPIO Input',  source: 'hw/buttons.py' },
  { peripheral: 'Pulsante Prev',             gpio: 13, physical_pin: 33, protocol: 'GPIO Input',  source: 'hw/buttons.py' },
  { peripheral: 'Pulsante Power',            gpio: 3,  physical_pin: 5,  protocol: 'GPIO Input',  source: 'hw/buttons.py' },
  { peripheral: 'LED WS2813',                gpio: 12, physical_pin: 32, protocol: 'PWM0',        source: 'hw/led.py'     },
  { peripheral: 'Amplificatore ON/OFF',      gpio: 20, physical_pin: 38, protocol: 'GPIO Output', source: 'hw/amp.py'     },
  { peripheral: 'Amplificatore Mute',        gpio: 26, physical_pin: 37, protocol: 'GPIO Output', source: 'hw/amp.py'     },
  { peripheral: 'RFID RC522 (CS)',           gpio: 8,  physical_pin: 24, protocol: 'SPI0',        source: 'hw/rfid.py'    },
  { peripheral: 'RFID RC522 (SCK)',          gpio: 11, physical_pin: 23, protocol: 'SPI0',        source: 'hw/rfid.py'    },
  { peripheral: 'RFID RC522 (MOSI)',         gpio: 10, physical_pin: 19, protocol: 'SPI0',        source: 'hw/rfid.py'    },
  { peripheral: 'RFID RC522 (MISO)',         gpio: 9,  physical_pin: 21, protocol: 'SPI0',        source: 'hw/rfid.py'    },
  { peripheral: 'Batteria MAX17048 (SDA)',   gpio: 2,  physical_pin: 3,  protocol: 'I2C1',        source: 'hw/battery.py' },
  { peripheral: 'Batteria MAX17048 (SCL)',   gpio: 3,  physical_pin: 5,  protocol: 'I2C1',        source: 'hw/battery.py' },
]

const pinout = ref([...STATIC_PINOUT])

// Pin fisici usati, per il diagramma ASCII
const USED_PINS = new Set(STATIC_PINOUT.map(p => p.physical_pin))

// Layout header 40 pin: [odd, even] per ogni riga
const HEADER_ROWS = [
  [1,  2 ], [3,  4 ], [5,  6 ], [7,  8 ], [9,  10],
  [11, 12], [13, 14], [15, 16], [17, 18], [19, 20],
  [21, 22], [23, 24], [25, 26], [27, 28], [29, 30],
  [31, 32], [33, 34], [35, 36], [37, 38], [39, 40],
]

function pinLabel(n) {
  if (USED_PINS.has(n)) {
    const entry = STATIC_PINOUT.find(p => p.physical_pin === n)
    if (entry) {
      const short = entry.peripheral
        .replace('Pulsante ', 'BTN ')
        .replace('Amplificatore ', 'AMP ')
        .replace('Batteria MAX17048 ', 'BAT ')
        .replace('RFID RC522 ', 'RFID ')
        .replace('LED WS2813', 'LED')
      return `[${String(n).padStart(2)}] ${short}`
    }
  }
  return ` (${String(n).padStart(2)}) —`
}

const asciiDiagram = HEADER_ROWS.map(([l, r]) => {
  const left  = pinLabel(l).padEnd(32)
  const right = pinLabel(r)
  return `${left}│ ${right}`
}).join('\n')

async function loadPinout() {
  loading.value = true
  try {
    const api = getApi()
    const { data } = await guardedCall(() => api.get('/gpio/pinout'))
    if (data && data.pinout) {
      pinout.value = data.pinout
      notes.value = data.notes || []
    }
  } catch (e) {
    // Backend non disponibile — usiamo i dati statici già impostati
    console.warn('GPIO pinout: fallback ai dati statici —', extractApiError(e))
  } finally {
    loading.value = false
  }
}

function protocolClass(protocol) {
  if (!protocol) return ''
  const p = protocol.toUpperCase()
  if (p.startsWith('GPIO INPUT'))  return 'badge-gpio-input'
  if (p.startsWith('GPIO OUTPUT')) return 'badge-gpio-output'
  if (p.startsWith('PWM'))         return 'badge-pwm'
  if (p.startsWith('SPI'))         return 'badge-spi'
  if (p.startsWith('I2C'))         return 'badge-i2c'
  return 'badge-default'
}

onMounted(loadPinout)
</script>

<style scoped>
.admin-gpio-pinout {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.header-section h2 { margin: 0; color: #fff; }
.header-section p  { color: #aaa; margin: 5px 0 0 0; }

/* ── Card base (coerente con AdminDiagnostics) ── */
.card {
  background: #2a2a35;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #3a3a48;
  padding-bottom: 10px;
  margin-bottom: 15px;
  flex-wrap: wrap;
  gap: 8px;
}

.card-header h3 { margin: 0; color: #ffd27b; }

.btn-refresh {
  background: transparent;
  border: 1px solid #555;
  color: #ccc;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
}
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }

.loading-text {
  color: #aaa;
  font-style: italic;
  text-align: center;
  padding: 20px 0;
}

/* ── Pinout table ── */
.table-wrapper { overflow-x: auto; }

.pinout-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}

.pinout-table th {
  background: #1a1a24;
  color: #aaa;
  padding: 8px 12px;
  text-align: left;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid #3a3a48;
}

.pinout-table td {
  padding: 8px 12px;
  border-bottom: 1px solid #2a2a38;
  color: #ddd;
  vertical-align: middle;
}

.pinout-table tr:hover td { background: #1e1e2a; }

.pin-peripheral { font-weight: bold; color: #fff; }
.pin-gpio       { color: #ffd27b; font-family: monospace; white-space: nowrap; }
.pin-physical   { color: #aaa; font-family: monospace; }
.pin-source     { color: #7cb3ff; font-family: monospace; font-size: 0.82rem; }

/* ── Protocol badges ── */
.badge {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 10px;
  font-size: 0.75rem;
  font-weight: bold;
  white-space: nowrap;
}

.badge-gpio-input  { background: #0d2b14; color: #66bb6a; border: 1px solid #66bb6a; }
.badge-gpio-output { background: #2b1a00; color: #ffa726; border: 1px solid #ffa726; }
.badge-pwm         { background: #1c0a2e; color: #ba68c8; border: 1px solid #ba68c8; }
.badge-spi         { background: #002b2e; color: #4dd0e1; border: 1px solid #4dd0e1; }
.badge-i2c         { background: #2b2800; color: #fff176; border: 1px solid #fff176; }
.badge-default     { background: #1e1e26; color: #aaa;    border: 1px solid #555;    }

/* ── Legend ── */
.legend-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #1e1e26;
  border-radius: 8px;
  padding: 8px 14px;
}

.legend-desc { font-size: 0.85rem; color: #ccc; }

/* ── Notes ── */
.notes-card .notes-list {
  margin: 0;
  padding-left: 20px;
  color: #ffd27b;
  font-size: 0.9rem;
  line-height: 1.6;
}

/* ── ASCII diagram ── */
.ascii-hint {
  color: #aaa;
  font-size: 0.82rem;
  margin: 0 0 10px 0;
}

.ascii-diagram {
  font-family: 'Courier New', Courier, monospace;
  font-size: 0.78rem;
  color: #b0e0ff;
  background: #111118;
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
  line-height: 1.5;
  white-space: pre;
  margin: 0;
}
</style>
