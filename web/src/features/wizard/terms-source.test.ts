import { describe, expect, it } from 'vitest'
import { deriveTermsSource } from './terms-source.ts'

describe('deriveTermsSource', () => {
  it('нет автоматических полей — MANUAL', () => {
    expect(deriveTermsSource({})).toBe('MANUAL')
    expect(deriveTermsSource({ purpose_code: 'MANUAL', term_months: 'MANUAL' })).toBe('MANUAL')
  })

  it('есть правила, нет ИИ — RULES_CONFIRMED', () => {
    expect(deriveTermsSource({ purpose_code: 'MANUAL', requested_amount_rub: 'RULES' })).toBe(
      'RULES_CONFIRMED',
    )
  })

  it('хотя бы одно поле от ИИ — LLM_CONFIRMED, даже рядом с правилами', () => {
    expect(
      deriveTermsSource({
        purpose_code: 'LLM',
        requested_amount_rub: 'RULES',
        term_months: 'MANUAL',
      }),
    ).toBe('LLM_CONFIRMED')
  })
})
