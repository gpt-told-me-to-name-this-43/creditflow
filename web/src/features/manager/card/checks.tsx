import type { Provider } from '@/api/enums.ts'
import type { components } from '@/api/schema.d.ts'
import { Badge } from '@/components/ui/badge.tsx'
import {
  cardTexts,
  checksTexts,
  providerTexts,
  sourceSummaryLabels,
  sourceValueTexts,
} from '@/content/manager.ts'
import { formatDateTime } from '@/lib/dates.ts'
import { formatMoney } from '@/lib/money.ts'

type Schemas = components['schemas']
type JsonValue = Schemas['JsonValue']

/** Какие источники подсвечивать: по кодам из ответа API, сами значения фронт не оценивает. */
function attentionProviders(
  proposal: Schemas['Proposal'] | null,
  scoring: Schemas['Scoring'] | null,
) {
  const flagged = new Set<Provider>()
  for (const code of proposal?.blocking_codes ?? []) {
    if (code === 'COMPANY_INACTIVE' || code === 'APPLICANT_NOT_AUTHORIZED') {
      flagged.add('EGRUL').add('EGRIP')
    }
    if (code === 'BANKRUPTCY_PROCEEDING' || code === 'ACCOUNT_BLOCKED_BY_FNS') flagged.add('FNS')
    if (code === 'ACCOUNT_HISTORY_INSUFFICIENT') flagged.add('BANK')
  }
  if (scoring?.reason_codes.some((code) => code.startsWith('CREDIT_HISTORY_'))) flagged.add('BKI')
  return flagged
}

function formatValue(key: string, value: JsonValue): string {
  if (value === null) return '—'
  if (typeof value === 'string' && key.endsWith('_rub'))
    return formatMoney(value, { kopecks: false })
  if (typeof value === 'object' && !Array.isArray(value)) {
    // Руководитель: «ФИО, ИНН …».
    const { full_name, inn } = value as { full_name?: JsonValue; inn?: JsonValue }
    if (typeof full_name === 'string') return inn ? `${full_name}, ИНН ${String(inn)}` : full_name
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return value.map(String).join(', ')
  return sourceValueTexts[String(value)] ?? String(value)
}

export function ExternalChecks({
  sources,
  proposal,
  scoring,
}: {
  sources: Schemas['ExternalSource'][]
  proposal: Schemas['Proposal'] | null
  scoring: Schemas['Scoring'] | null
}) {
  const flagged = attentionProviders(proposal, scoring)
  return (
    <section aria-labelledby="checks-title" className="grid gap-4 rounded-xl border bg-card p-6">
      <h2 id="checks-title" className="text-xl font-semibold">
        {cardTexts.checks}
      </h2>
      {sources.length === 0 ? (
        <p className="text-muted-foreground">{cardTexts.checksEmpty}</p>
      ) : (
        <ul className="grid grid-cols-2 gap-4">
          {sources.map((source) => {
            const attention = flagged.has(source.provider)
            return (
              <li
                key={source.provider}
                className={
                  attention
                    ? 'grid content-start gap-3 rounded-lg border border-destructive p-4'
                    : 'grid content-start gap-3 rounded-lg border p-4'
                }
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">{providerTexts[source.provider]}</h3>
                  <Badge variant={attention ? 'destructive' : 'outline'}>
                    {attention ? checksTexts.attention : checksTexts.ok}
                  </Badge>
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                  {Object.entries(source.summary).map(([key, value]) => (
                    <div key={key} className="contents">
                      <dt className="text-muted-foreground">{sourceSummaryLabels[key] ?? key}</dt>
                      <dd className="font-medium">{formatValue(key, value)}</dd>
                    </div>
                  ))}
                </dl>
                <p className="text-xs text-muted-foreground">
                  {cardTexts.fetchedAt(formatDateTime(source.fetched_at))}
                </p>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
