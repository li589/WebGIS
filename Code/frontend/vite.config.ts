import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    // MapLibre is large even when isolated, so raise the warning threshold
    // after splitting framework/export libraries into separate chunks.
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined

          if (id.includes('maplibre-gl')) return 'vendor-maplibre'
          if (id.includes('html2canvas')) return 'vendor-html2canvas'
          if (id.includes('jspdf')) return 'vendor-jspdf'
          if (id.includes('vue') || id.includes('pinia')) return 'vendor-framework'

          return undefined
        },
      },
    },
  },
})
