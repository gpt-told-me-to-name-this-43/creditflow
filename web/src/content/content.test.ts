import { describe, expect, it } from 'vitest'
import {
  APPLICATION_STATUSES,
  CLIENT_REASON_CODES,
  ERROR_CODES,
  PURPOSE_CODES,
} from '@/api/enums.ts'
import { demoScenarioTexts, demoTexts } from './demo.ts'
import {
  bindingErrors,
  errorMessages,
  networkErrorMessage,
  pageErrors,
  unknownErrorMessage,
} from './errors.ts'
import { glossary } from './glossary.ts'
import { purposeTexts } from './purposes.ts'
import { reasonTexts } from './reasons.ts'
import { statusTexts } from './statuses.ts'

describe('полнота content/ против перечислений контракта', () => {
  it.each([
    ['статусы', statusTexts, APPLICATION_STATUSES],
    ['причины отказа', reasonTexts, CLIENT_REASON_CODES],
    ['цели', purposeTexts, PURPOSE_CODES],
    ['ошибки', errorMessages, ERROR_CODES],
  ] as const)('%s: текст есть для каждого значения и нет лишних', (_name, texts, values) => {
    expect(Object.keys(texts).sort()).toEqual([...values].sort())
  })
})

// Клиент не видит внутренних метрик и кодов (#9). Пока проверяем сами тексты;
// тест по отрендеренным экранам появится вместе с экранами.
const FORBIDDEN = [/скоринг/i, /\bscore\b/i, /dscr/i, /лимит/i]
const LATIN_CODE = /\b[A-Z][A-Z_]{2,}\b/

function collectStrings(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (value && typeof value === 'object') return Object.values(value).flatMap(collectStrings)
  return []
}

describe('тексты для клиента', () => {
  const texts = collectStrings([
    statusTexts,
    reasonTexts,
    purposeTexts,
    errorMessages,
    pageErrors,
    bindingErrors,
    demoScenarioTexts,
    demoTexts,
    glossary,
    networkErrorMessage,
    unknownErrorMessage,
  ])

  it.each(texts)('без внутренних терминов и кодов: %s', (text) => {
    for (const word of FORBIDDEN) expect(text).not.toMatch(word)
    expect(text).not.toMatch(LATIN_CODE)
  })
})
