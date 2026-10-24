import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyTheme, resolveTheme, setTheme } from './theme.ts'

function mockSystemDark(dark: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches: dark, addEventListener: vi.fn() })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  applyTheme('light')
})

describe('theme', () => {
  it('по умолчанию следует за системой', () => {
    mockSystemDark(true)
    expect(resolveTheme()).toBe('dark')
    mockSystemDark(false)
    expect(resolveTheme()).toBe('light')
  })

  it('выбор пользователя важнее системы и запоминается', () => {
    mockSystemDark(true)
    setTheme('light')
    expect(resolveTheme()).toBe('light')
    expect(localStorage.getItem('creditflow.theme')).toBe('light')
  })

  it('тёмная тема — класс dark на html', () => {
    applyTheme('dark')
    expect(document.documentElement).toHaveClass('dark')
    applyTheme('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })
})
