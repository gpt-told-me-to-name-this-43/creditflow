import { describe, expect, it } from 'vitest'
import { isValidInn, normalizeInn } from './inn.ts'

describe('normalizeInn', () => {
  it('оставляет только цифры и обрезает до 12', () => {
    expect(normalizeInn('7707 083-893')).toBe('7707083893')
    expect(normalizeInn('5001007322591234')).toBe('500100732259')
    expect(normalizeInn('абв')).toBe('')
  })
})

describe('isValidInn', () => {
  it('принимает корректные ИНН организации и ИП', () => {
    expect(isValidInn('7707083893')).toBe(true)
    expect(isValidInn('500100732259')).toBe(true)
  })

  it('отклоняет неверную контрольную цифру', () => {
    expect(isValidInn('7707083894')).toBe(false)
    expect(isValidInn('500100732258')).toBe(false)
  })

  it('отклоняет неверную длину и не цифры', () => {
    expect(isValidInn('')).toBe(false)
    expect(isValidInn('77070838')).toBe(false)
    expect(isValidInn('77070838931')).toBe(false)
    expect(isValidInn('770708389a')).toBe(false)
  })
})
