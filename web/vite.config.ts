import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { loadEnv, type Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

const WORKER = 'mockServiceWorker.js'

// Воркер MSW лежит в msw/, а не в public/: в обычную сборку он не копируется.
// Под VITE_API_MOCKS=1 его раздаёт dev-сервер и кладёт в dist сборка на моках.
function mockServiceWorker(enabled: boolean): Plugin {
  const source = () => readFileSync(new URL(`./msw/${WORKER}`, import.meta.url), 'utf8')
  return {
    name: 'creditflow:msw-worker',
    configureServer(server) {
      if (!enabled) return
      server.middlewares.use(`/${WORKER}`, (_req, res) => {
        res.setHeader('Content-Type', 'text/javascript')
        res.end(source())
      })
    },
    generateBundle() {
      if (enabled) this.emitFile({ type: 'asset', fileName: WORKER, source: source() })
    },
  }
}

// `pnpm dev` проксирует /api на api из `make dev` — тот же origin, что и за nginx.
export default defineConfig(({ mode }) => ({
  // Плагин роутера генерирует src/routeTree.gen.ts и должен идти до react().
  plugins: [
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    mockServiceWorker(loadEnv(mode, process.cwd(), 'VITE_').VITE_API_MOCKS === '1'),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // e2e/ — Playwright против живого стека (`pnpm e2e`), не vitest.
    include: ['src/**/*.test.{ts,tsx}'],
  },
}))
