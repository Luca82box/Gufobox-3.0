import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(router)
app.mount('#app')

// Rimuovi lo splash screen dopo il mount dell'app Vue
const splash = document.getElementById('splash-screen')
if (splash) {
  splash.style.opacity = '0'
  setTimeout(() => splash.remove(), 500)
}
