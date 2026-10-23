import { describe, expect, it } from 'vitest'
import type { components } from '@/api/schema.d.ts'
import { offerRows, offerSummary } from './offer.ts'

type Application = components['schemas']['ClientApplicationView']

const plain = (s: string | null | undefined) => s?.replaceAll('\u00a0', ' ')

const application = {
  requested_amount_rub: '3000000.00',
  term_months: 36,
  annual_rate_pct: '24.00',
  monthly_payment_rub: '117698.56',
  overpayment_rub: '1237148.16',
} as Application

describe('встречное предложение', () => {
  it('помечает только изменённые условия', () => {
    const rows = offerRows(application, {
      amount_rub: '2340000.00',
      term_months: 36,
      annual_rate_pct: '24.00',
      monthly_payment_rub: '91804.88',
      overpayment_rub: '964975.68',
    })
    expect(rows.map((row) => [row.label, row.changed])).toEqual([
      ['Сумма', true],
      ['Срок', false],
      ['Ставка', false],
      ['Платёж в месяц', true],
      ['Переплата за весь срок', true],
    ])
    expect(plain(rows[0]?.offered)).toBe('2 340 000,00 ₽')
  })

  it('дольше срок: платёж меньше, переплата больше — разница сумм до копейки', () => {
    const summary = offerSummary(application, {
      amount_rub: '3000000.00',
      term_months: 54,
      annual_rate_pct: '24.00',
      monthly_payment_rub: '86016.04',
      overpayment_rub: '1644866.16',
    })
    expect(plain(summary)).toBe('Платёж меньше на 31 682,52 ₽, переплата больше на 407 718,00 ₽')
  })

  it('меньше сумма: платёж и переплата меньше', () => {
    const summary = offerSummary(application, {
      amount_rub: '2340000.00',
      term_months: 36,
      annual_rate_pct: '24.00',
      monthly_payment_rub: '91804.88',
      overpayment_rub: '964975.68',
    })
    expect(plain(summary)).toBe('Платёж меньше на 25 893,68 ₽, переплата меньше на 272 172,48 ₽')
  })
})
