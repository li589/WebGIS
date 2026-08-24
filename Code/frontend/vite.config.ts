import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
  const config = {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    server: {
      // 机构演示/临时排障：设 VITE_HIDE_ERROR_OVERLAY=1 关闭红屏叠加层，避免把源码片段打到屏幕上。
      // 日常本地开发默认保持 overlay，便于立刻看到编译/运行错误。
      hmr: {
        overlay: !['1', 'true', 'yes', 'on'].includes(
          (env.VITE_HIDE_ERROR_OVERLAY || '').trim().toLowerCase(),
        ),
      },
      fs: {
        // 允许加载仓库根下的 Test/frontend/（测试已迁出 src/）。
        allow: [path.resolve(__dirname, '../..')],
      },
      proxy: {
        // API 请求代理到后端
        // 注意：前端 runtime-api.ts 中所有请求路径均无 /api 前缀，
        // 因此 proxy 改为拦截实际使用的路径（与 runtime-api.ts 保持一致）。
        // /api 例外：remote browser（/api/remote/*）在 remote_browser_router 挂载。
        '/api': { target: apiTarget, changeOrigin: true },
        '/workflow-runs': { target: apiTarget, changeOrigin: true },
        '/workflow-definitions': { target: apiTarget, changeOrigin: true },
        '/workflow-node-templates': { target: apiTarget, changeOrigin: true },
        '/workflow-timers': { target: apiTarget, changeOrigin: true },
        '/cleanup': { target: apiTarget, changeOrigin: true },
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
        // 时间序列/栅格 XYZ 数据瓦片。缺少该代理时 Vite 会返回 index.html（200 text/html），
        // MapLibre 将其当 PNG 解码失败，表现为“图层存在但地图无内容”。
        '/overlay-tiles': { target: apiTarget, changeOrigin: true },
        '/overlay-preview': { target: apiTarget, changeOrigin: true },
        '/overlay-bounds': { target: apiTarget, changeOrigin: true },
        '/overlay-value': { target: apiTarget, changeOrigin: true },
        // 图层平台 P0：统一图层资产工作流（POST）。缺代理时 POST 打到 Vite
        // dev server 自身 → 405 Method Not Allowed（添加图层直接报错）。
        '/overlay-asset-workflows': { target: apiTarget, changeOrigin: true },
        // 图层平台 P1：在线源同步（POST /layer-assets/{id}/sync）与课题组
        // 模板（GET/POST /workflows/templates*）。缺代理同上 405/HTML 假响应。
        '/layer-assets': { target: apiTarget, changeOrigin: true },
        '/workflows': { target: apiTarget, changeOrigin: true },
        '/overlays': { target: apiTarget, changeOrigin: true },
        '/import': { target: apiTarget, changeOrigin: true },
        '/export': { target: apiTarget, changeOrigin: true },
        '/auth': { target: apiTarget, changeOrigin: true },
        '/workspace': { target: apiTarget, changeOrigin: true },
        '/analysis': { target: apiTarget, changeOrigin: true },
        // 问题反馈 API（与网关 /feedback/api/* 同路径；静态反馈页仅在 gateway 剖面）
        '/feedback/api': { target: apiTarget, changeOrigin: true },
        '/health': { target: apiTarget, changeOrigin: true },
      },
      allowedHosts: ['geoflow.cgdas.dpdns.org'],
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
    test: {
      // 测试已迁出 src/，集中到仓库根 Test/frontend/（保留 src 目录结构）。
      // 相对导入已改写为 @/ 别名（@ → Code/frontend/src，仍由 resolve.alias 解析）。
      // 保持 vite root = Code/frontend/，使 bare import（vue/vitest/pinia）经
      // Code/frontend/node_modules 解析；include 用 ../../ 跨出 root，配合 server.fs.allow。
      include: ['../../Test/frontend/**/*.test.ts'],
      // P0-4：前端覆盖率配置（W3.4 覆盖率门：22% → 30%+，阈值锁定当前基线防倒退）
      coverage: {
        provider: 'v8' as const,
        reporter: ['text', 'lcov'],
        include: ['src/**/*.{ts,vue}'],
        exclude: ['src/types/api-contracts.ts', 'src/**/*.d.ts'],
        thresholds: {
          lines: 32,
          statements: 30,
          branches: 25,
          functions: 28,
        },
      },
    },
  }
  return config
})
