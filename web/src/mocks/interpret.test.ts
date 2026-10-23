import { describe, expect, it } from 'vitest'
import { CLARIFICATION_QUESTION, interpret } from './interpret.ts'

describe('распознавание потребности в моках', () => {
  it('«Нужно 2 млн на 3 года на новую печь»: все три поля', () => {
    expect(interpret('Нужно 2 млн на 3 года на новую печь', true)).toEqual({
      status: 'OK',
      clarification_question: null,
      suggestion: {
        purpose_code: { value: 'EQUIPMENT', source: 'LLM', matched_text: 'печь' },
        requested_amount_rub: { value: 2_000_000, source: 'RULES', matched_text: '2 млн' },
        term_months: { value: 36, source: 'RULES', matched_text: 'на 3 года' },
      },
    })
  })

  it.each([
    ['1,5 млн на 18 месяцев на ремонт', 1_500_000, 18, 'RENOVATION'],
    ['500 тыс на полгода закупить товар', 500_000, 6, 'INVENTORY'],
    ['3 000 000 ₽ на год на зарплаты', 3_000_000, 12, 'WORKING_CAPITAL'],
  ])('%s', (text, amount, term, purpose) => {
    const { suggestion } = interpret(text, true)
    expect(suggestion.requested_amount_rub?.value).toBe(amount)
    expect(suggestion.term_months?.value).toBe(term)
    expect(suggestion.purpose_code?.value).toBe(purpose)
  })

  it('не хватает данных — уточняющий вопрос', () => {
    expect(interpret('хочу кредит', true)).toMatchObject({
      status: 'NEEDS_CLARIFICATION',
      clarification_question: CLARIFICATION_QUESTION,
    })
  })

  it('ИИ недоступен — только правила', () => {
    const result = interpret('2 млн на 3 года на печь', false)
    expect(result.status).toBe('UNAVAILABLE')
    expect(result.suggestion.purpose_code?.source).toBe('RULES')
  })
})
