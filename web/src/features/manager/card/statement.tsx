import { useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { cardTexts } from '@/content/manager.ts'
import { formatMonth } from '@/lib/dates.ts'
import { formatMoney, rublesToNumber, wholeRubles } from '@/lib/money.ts'

type Scoring = components['schemas']['Scoring']

// Три серии в одних единицах (₽) — одна ось. Порядок цветов фиксирован, легенда и
// таблица всегда доступны: третий цвет на светлом фоне ниже 3:1.
const SERIES = [
  { key: 'revenue_rub', label: cardTexts.revenue, color: 'var(--chart-1)' },
  { key: 'opex_rub', label: cardTexts.opex, color: 'var(--chart-2)' },
  { key: 'debt_svc_rub', label: cardTexts.debtSvc, color: 'var(--chart-3)' },
] as const

/** Только для осей графика: целые рубли числом. Расчёты на фронте не ведём. */
const plotValue = (value: string) => rublesToNumber(wholeRubles(value))

const axisMoney = new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 })

export function Statement({ scoring }: { scoring: Scoring }) {
  const [table, setTable] = useState(false)
  const data = scoring.monthly.map((month) => ({
    month: formatMonth(month.month),
    revenue_rub: plotValue(month.revenue_rub),
    opex_rub: plotValue(month.opex_rub),
    debt_svc_rub: plotValue(month.debt_svc_rub),
  }))

  return (
    <section aria-labelledby="statement-title" className="grid gap-4 rounded-xl border bg-card p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 id="statement-title" className="text-xl font-semibold">
          {cardTexts.statement}
        </h2>
        <Button variant="outline" size="sm" onClick={() => setTable((value) => !value)}>
          {table ? cardTexts.showChart : cardTexts.showTable}
        </Button>
      </div>

      <dl className="grid grid-cols-5 gap-4 text-sm">
        <Figure
          label={cardTexts.cfads}
          value={
            scoring.cfads_monthly_rub
              ? formatMoney(scoring.cfads_monthly_rub, { kopecks: false })
              : '—'
          }
        />
        <Figure
          label={cardTexts.revenueChange}
          value={scoring.revenue_change_pct ? `${scoring.revenue_change_pct} %` : '—'}
        />
        <Figure
          label={cardTexts.debt}
          value={formatMoney(scoring.existing_debt_payments_rub, { kopecks: false })}
        />
        <Figure label={cardTexts.age} value={cardTexts.months(scoring.business_age_months)} />
        <Figure
          label={cardTexts.historyMonths}
          value={cardTexts.months(scoring.account_history_months)}
        />
      </dl>

      {table || data.length === 0 ? (
        <table className="w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 font-medium">{cardTexts.month}</th>
              {SERIES.map((series) => (
                <th key={series.key} className="py-2 text-right font-medium">
                  {series.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {scoring.monthly.map((month) => (
              <tr key={month.month} className="border-b last:border-0">
                <td className="py-2">{formatMonth(month.month)}</td>
                {SERIES.map((series) => (
                  <td key={series.key} className="py-2 text-right tabular-nums">
                    {formatMoney(month[series.key], { kopecks: false })}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="h-72" role="img" aria-label={cardTexts.statement}>
          <ResponsiveContainer
            width="100%"
            height="100%"
            initialDimension={{ width: 800, height: 288 }}
          >
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
                tickLine={false}
                axisLine={{ stroke: 'var(--border)' }}
              />
              <YAxis
                tickFormatter={(value: number) => axisMoney.format(value)}
                tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                width={56}
              />
              <Tooltip
                formatter={(value) => formatMoney(`${String(value)}.00`, { kopecks: false })}
                contentStyle={{
                  background: 'var(--popover)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  color: 'var(--popover-foreground)',
                }}
                labelStyle={{ color: 'var(--popover-foreground)', fontWeight: 600 }}
              />
              <Legend
                iconType="plainline"
                wrapperStyle={{ color: 'var(--foreground)', fontSize: 14 }}
              />
              {SERIES.map((series) => (
                <Line
                  key={series.key}
                  dataKey={series.key}
                  name={series.label}
                  stroke={series.color}
                  strokeWidth={2}
                  dot={{ r: 3, strokeWidth: 2, fill: 'var(--card)' }}
                  activeDot={{ r: 5 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-base font-semibold tabular-nums">{value}</dd>
    </div>
  )
}
