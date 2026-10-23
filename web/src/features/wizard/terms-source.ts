import type { components } from '@/api/schema.d.ts'

type Schemas = components['schemas']

/**
 * Сводный источник условий, как его выводит бэк (design §3.3): хотя бы одно поле от LLM —
 * `LLM_CONFIRMED`, иначе хотя бы одно от правил — `RULES_CONFIRMED`, иначе `MANUAL`.
 * На фронте только для подсказки до сохранения; в заявке — значение с бэка.
 */
export function deriveTermsSource(
  sources: Partial<Record<string, Schemas['FieldSource']>>,
): Schemas['TermsSource'] {
  const values = Object.values(sources)
  if (values.includes('LLM')) return 'LLM_CONFIRMED'
  if (values.includes('RULES')) return 'RULES_CONFIRMED'
  return 'MANUAL'
}
