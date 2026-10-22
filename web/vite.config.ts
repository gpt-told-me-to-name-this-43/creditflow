import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// `pnpm dev` проксирует /api на api из `make dev` — тот же origin, что и за nginx.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'node',
  },
})
