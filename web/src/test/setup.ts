import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { resetDb } from '@/mocks/db.ts'
import { resetScenario } from '@/mocks/scenarios.ts'
import { server } from './server.ts'

// jsdom не умеет scrollTo, а роутер вызывает его при восстановлении прокрутки.
window.scrollTo = () => {}

// jsdom без ResizeObserver, а Radix (чекбокс, тултип) измеряет им размеры.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Запрос без обработчика роняет тест: значит, мок забыли добавить.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))

afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetScenario()
  resetDb()
  sessionStorage.clear()
  localStorage.clear()
})

afterAll(() => server.close())
