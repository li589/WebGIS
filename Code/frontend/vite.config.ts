import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
  const config = {
    plugins: [vue()],
    server: {
      proxy: {
        // API 请求代理到后端
        // 注意：前端 runtime-api.ts 中所有请求路径均无 /api 前缀，
        // 因此 proxy 改为拦截实际使用的路径（与 runtime-api.ts 保持一致）
        '/workflow-runs': { target: apiTarget, changeOrigin: true },
        '/layers': { target: apiTarget, changeOrigin: true },
        '/weather': { target: apiTarget, changeOrigin: true },
        '/artifacts': { target: apiTarget, changeOrigin: true },
        '/gee': { target: apiTarget, changeOrigin: true },
        '/system': { target: apiTarget, changeOrigin: true },
        '/provider': { target: apiTarget, changeOrigin: true },
        '/runtime': { target: apiTarget, changeOrigin: true },
        '/frontend': { target: apiTarget, changeOrigin: true },
        '/config': { target: apiTarget, changeOrigin: true },
        '/unified-tiles': { target: apiTarget, changeOrigin: true },
        '/overlay-preview': { target: apiTarget, changeOrigin: true },
        '/overlay-bounds': { target: apiTarget, changeOrigin: true },
        '/overlays': { target: apiTarget, changeOrigin: true },
        '/import': { target: apiTarget, changeOrigin: true },
      },
    },
    build: {
      // MapLibre is large even when isolated, so raise the warning threshold
      // after splitting framework/export libraries into separate chunks.
      chunkSizeWarningLimit: 1100,
      rollupOptions: {
        output: {
          manualChunks(id: string) {
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
  }
  return config
})
