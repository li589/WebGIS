import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'maplibre-gl/dist/maplibre-gl.css'

import App from './App.vue'
import { router } from './app/router'
import { BRAND } from './ui-copy/brand'
import './styles/main.css'
import { bootstrapMotionPreference } from './services/motion-preference'
import { installClientErrorCapture } from './utils/client-error-capture'
import { clearChunkReloadFlag } from './utils/lazy-chunk'
import { installPerfGlobal } from './utils/perf-probe'

import { vSpotlight } from './directives/spotlight'

installPerfGlobal()
clearChunkReloadFlag()
bootstrapMotionPreference()

document.title = BRAND.fullName

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.directive('spotlight', vSpotlight)
installClientErrorCapture(app)

app.mount('#app')
