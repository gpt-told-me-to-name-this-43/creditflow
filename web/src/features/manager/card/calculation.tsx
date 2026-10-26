import type { ReactNode } from 'react'
import type { components } from '@/api/schema.d.ts'
import { Badge } from '@/components/ui/badge.tsx'
import { cardTexts, reasonCodeTexts, riskLevelTexts, scoreFactors } from '@/content/manager.ts'
import { formatMoney } from '@/lib/money.ts'

type Scoring = components['schemas']['Scoring']

/** Расчёт RiskEngine по запрошенным условиям: всё — из ответа API, фронт ничего не считает. */
export function Calculation({ scoring }: { scoring: Scoring }) {
  if (scoring.calculation_status === 'SKIPPED') {
    return (
      <section aria-labelledby="calc-title" className="grid gap-3 rounded-xl border bg-card p-6">
        <h2 id="calc-title" className="text-xl font-semibold">
          {cardTexts.calculation}
        </h2>
        <p className="text-muted-foreground">{cardTexts.skipped(scoring.account_history_months)}</p>
      </section>
    )
  }

  // Порог DSCR — по кодам причин из API, а не сравнением на фронте.
  const meetsTarget = scoring.positive_codes.includes('DSCR_MEETS_TARGET')

  return (
    <section aria-labelledby="calc-title" className="grid gap-6 rounded-xl border bg-card p-6">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="calc-title" className="text-xl font-semibold">
          {cardTexts.calculation}
        </h2>
        <span className="text-xs text-muted-foreground">{scoring.engine_version}</span>
      </div>

      <dl className="grid grid-cols-4 gap-4">
        <Metric
          label={cardTexts.payment}
          value={scoring.monthly_payment_rub ? formatMoney(scoring.monthly_payment_rub) : '—'}
        />
        <Metric
          label={cardTexts.dscr}
          value={scoring.dscr ?? '—'}
          note={
            <Badge variant={meetsTarget ? 'success' : 'destructive'}>
              {meetsTarget ? cardTexts.dscrAbove : cardTexts.dscrBelow}
            </Badge>
          }
          hint={cardTexts.dscrTarget}
        />
        <Metric
          label={cardTexts.risk}
          value={scoring.risk_level ? riskLevelTexts[scoring.risk_level] : '—'}
        />
        <Metric
          label={cardTexts.limit}
          value={
            scoring.limit_rub
              ? formatMoney(scoring.limit_rub, { kopecks: false })
              : cardTexts.noLimit
          }
        />
      </dl>

      <div className="grid gap-3">
        <div className="flex items-baseline gap-3">
          <h3 className="font-semibold">{cardTexts.score}</h3>
          <span className="text-2xl font-bold tabular-nums">{scoring.score ?? '—'}</span>
          <span className="text-sm text-muted-foreground">/ 100</span>
        </div>
        <ul className="grid grid-cols-2 gap-x-8 gap-y-3">
          {scoreFactors.map((factor) => {
            const points = scoring.factor_points?.[factor.key] ?? 0
            return (
              <li key={factor.key} className="grid gap-1">
                <div className="flex justify-between text-sm">
                  <span>{factor.label}</span>
                  <span className="font-semibold tabular-nums">
                    {cardTexts.scoreOf(points, factor.max)}
                  </span>
                </div>
                <span aria-hidden className="h-2 overflow-hidden rounded-full bg-muted">
                  <span
                    className="block h-full rounded-full bg-chart-1"
                    style={{ width: `${(points / factor.max) * 100}%` }}
                  />
                </span>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <Codes title={cardTexts.riskCodes} codes={scoring.reason_codes} />
        <Codes title={cardTexts.positiveCodes} codes={scoring.positive_codes} />
      </div>
    </section>
  )
}

function Metric({
  label,
  value,
  note,
  hint,
}: {
  label: string
  value: string
  note?: ReactNode
  hint?: string
}) {
  return (
    <div className="grid content-start gap-1">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="flex flex-wrap items-center gap-2 text-xl font-bold tabular-nums">
        {value}
        {note}
      </dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </div>
  )
}

function Codes({ title, codes }: { title: string; codes: Scoring['reason_codes'] }) {
  return (
    <div className="grid content-start gap-2">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      {codes.length === 0 ? (
        <p className="text-sm text-muted-foreground">{cardTexts.no}</p>
      ) : (
        <ul className="grid gap-1 text-sm">
          {codes.map((code) => (
            <li key={code}>{reasonCodeTexts[code]}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
