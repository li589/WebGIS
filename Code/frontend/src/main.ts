import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'maplibre-gl/dist/maplibre-gl.css'

import App from './App.vue'
import { router } from './app/router'
import './styles/main.css'
import { installPerfGlobal } from './utils/perf-probe'

installPerfGlobal()

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')

