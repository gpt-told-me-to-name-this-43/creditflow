import { describe, expect, it } from 'vitest'
import { formatDate, formatDateTime } from './dates.ts'

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
