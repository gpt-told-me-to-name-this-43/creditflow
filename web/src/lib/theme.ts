import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'creditflow.theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

let current: Theme = 'light'
const listeners = new Set<() => void>()

function readStored(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    // хранилище недоступно (приватный режим) — живём на системной теме
    return null
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.(DARK_QUERY).matches ? 'dark' : 'light'
}

/** Выбор пользователя из localStorage, иначе — системная тема. */
export function resolveTheme(): Theme {
  return readStored() ?? systemTheme()
}

export function applyTheme(theme: Theme) {
  current = theme
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
  listeners.forEach((notify) => notify())
}

/** Явный выбор пользователя: запоминается и перестаёт следовать за системой. */
export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // не запомнится, но применится до перезагрузки
  }
  applyTheme(theme)
}

/** Вызывается один раз до первого рендера. */
export function initTheme() {
  applyTheme(resolveTheme())
  window.matchMedia?.(DARK_QUERY).addEventListener('change', () => {
    if (!readStored()) applyTheme(systemTheme())
  })
}

function subscribe(notify: () => void) {
  listeners.add(notify)
  return () => listeners.delete(notify)
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, () => current)
}
