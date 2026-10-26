import { describe, expect, it } from 'vitest'
import {
  formatCountdown,
  formatDate,
  formatDateTime,
  formatDuration,
  formatMonth,
  secondsUntil,
} from './dates.ts'

describe('formatDate', () => {
  it('показывает дату по Москве', () => {
    // 21:30 UTC — уже следующий день в Москве (UTC+3)
    expect(formatDate('2026-10-23T21:30:00Z')).toBe('24 октября 2026 г.')
    expect(formatDate('2026-10-23T10:00:00+00:00')).toBe('23 октября 2026 г.')
  })

  it('календарную дату не сдвигает по поясу', () => {
    expect(formatDate('2026-11-23')).toBe('23 ноября 2026 г.')
    expect(formatDate('2027-01-01')).toBe('1 января 2027 г.')
  })
})

describe('formatDateTime', () => {
  it('показывает время по Москве', () => {
    const text = formatDateTime('2026-10-23T12:42:00Z')
    expect(text).toContain('23 октября 2026 г.')
    expect(text).toContain('15:42')
  })
})

describe('таймер кода', () => {
  it('secondsUntil округляет вверх и не уходит в минус', () => {
    const now = Date.parse('2026-10-24T10:00:00Z')
    expect(secondsUntil('2026-10-24T10:05:00Z', now)).toBe(300)
    expect(secondsUntil('2026-10-24T10:00:00.500Z', now)).toBe(1)
    expect(secondsUntil('2026-10-24T09:59:00Z', now)).toBe(0)
  })

  it('formatCountdown — минуты и секунды', () => {
    expect(formatCountdown(299)).toBe('4:59')
    expect(formatCountdown(60)).toBe('1:00')
    expect(formatCountdown(5)).toBe('0:05')
    expect(formatCountdown(-3)).toBe('0:00')
  })
})

describe('formatDuration', () => {
  it('минуты, часы и дни', () => {
    expect(formatDuration(10)).toBe('1 мин')
    expect(formatDuration(45 * 60)).toBe('45 мин')
    expect(formatDuration(90 * 60)).toBe('1 ч 30 мин')
    expect(formatDuration(3 * 3600)).toBe('3 ч')
    expect(formatDuration(50 * 3600)).toBe('2 дн')
  })
})

describe('formatMonth', () => {
  it('месяц выписки без сдвига по поясу', () => {
    expect(formatMonth('2025-10-01')).toBe('окт. 2025')
    expect(formatMonth('2026-01-01')).toBe('янв. 2026')
  })
})
