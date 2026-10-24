import type { PurposeCode } from '@/api/enums.ts'
import type { components } from '@/api/schema.d.ts'

/*
 * Распознавание потребности для моков: простые правила вместо rules/LLM из #8.
 * Цель «предлагает ИИ» (LLM), сумму и срок «распознают правила» (RULES) — так в демо видны
 * обе метки. Когда ИИ недоступен (`?mock=unavailable`), остаются только правила.
 */

type InterpretResponse = components['schemas']['InterpretResponse']
type Source = 'RULES' | 'LLM'

const PURPOSE_WORDS: [RegExp, PurposeCode][] = [
  [/печ[ьи]|станок|станк|оборудовани|техник|витрин|автомобил|машин/i, 'EQUIPMENT'],
  [/ремонт/i, 'RENOVATION'],
  [/филиал|точк|открыт|расширени|магазин/i, 'BUSINESS_EXPANSION'],
  [/товар|закуп|парти[юя]|сезон/i, 'INVENTORY'],
  [/поставщик|сырь|предоплат/i, 'SUPPLIERS'],
  [/зарплат|аренд|оборот|разрыв|налог/i, 'WORKING_CAPITAL'],
]

const AMOUNT_RE =
  /(\d+(?:[.,]\d+)?)\s*(млн|миллион\w*|тыс\w*|т\.?\s?р\.?)|(\d[\d\s]{4,}\d)\s*(?:₽|руб)/i
const TERM_RE = /(?:на\s+)?(\d+)\s*(года|год|лет|мес\w*)|на\s+(год|полгода|полтора\s+года)/i

function parseAmount(text: string) {
  const match = AMOUNT_RE.exec(text)
  if (!match) return null
  const [matched, number, unit, plain] = match
  if (plain) return { value: parseInt(plain.replace(/\s/g, ''), 10), matched_text: matched.trim() }
  const [whole = '0', fraction = ''] = (number ?? '0').split(/[.,]/)
  const multiplier = /^млн|^миллион/i.test(unit ?? '') ? 1_000_000 : 1_000
  const value =
    parseInt(whole, 10) * multiplier +
    Math.round((parseInt(fraction || '0', 10) * multiplier) / 10 ** fraction.length)
  return { value, matched_text: matched.trim() }
}

function parseTerm(text: string) {
  const match = TERM_RE.exec(text)
  if (!match) return null
  const [matched, number, unit, word] = match
  const words: Record<string, number> = { год: 12, полгода: 6, 'полтора года': 18 }
  const value = word
    ? (words[word.toLowerCase().replace(/\s+/g, ' ')] ?? 12)
    : parseInt(number ?? '0', 10) * (/^мес/i.test(unit ?? '') ? 1 : 12)
  return { value, matched_text: matched.trim() }
}

function parsePurpose(text: string) {
  for (const [re, value] of PURPOSE_WORDS) {
    const match = re.exec(text)
    if (match) return { value, matched_text: match[0] }
  }
  return null
}

export const CLARIFICATION_QUESTION = 'Какая сумма и на какой срок вам нужна?'

export function interpret(text: string, llmAvailable: boolean): InterpretResponse {
  const purposeSource: Source = llmAvailable ? 'LLM' : 'RULES'
  const purpose = parsePurpose(text)
  const amount = parseAmount(text)
  const term = parseTerm(text)
  const suggestion: InterpretResponse['suggestion'] = {
    purpose_code: purpose && { ...purpose, source: purposeSource },
    requested_amount_rub: amount && { ...amount, source: 'RULES' },
    term_months: term && { ...term, source: 'RULES' },
  }
  if (!llmAvailable) return { status: 'UNAVAILABLE', suggestion, clarification_question: null }
  if (!purpose || !amount || !term) {
    return {
      status: 'NEEDS_CLARIFICATION',
      suggestion,
      clarification_question: CLARIFICATION_QUESTION,
    }
  }
  return { status: 'OK', suggestion, clarification_question: null }
}
