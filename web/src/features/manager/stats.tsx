import { useSuspenseQuery } from '@tanstack/react-query'
import { SUGGESTED_ACTIONS } from '@/api/enums.ts'
import { managerStatsQuery } from '@/api/queries/manager.ts'
import type { components } from '@/api/schema.d.ts'
import { statsTexts, suggestedActionTexts } from '@/content/manager.ts'
import { formatDuration } from '@/lib/dates.ts'

type Stats = components['schemas']['ManagerStats']
type FeedbackGroup = components['schemas']['AiFeedbackGroup']

/** Меньше стольких оценок долю 👍 не показываем — выборка случайна (#10). */
const MIN_FEEDBACK = 5

/** Доля из API («0.75») → «75 %». Не деньги: точности number хватает. */
function formatShare(share: string): string {
  return `${Math.round(parseFloat(share) * 100)}\u00A0%`
}

function feedbackShare(groups: FeedbackGroup[]) {
  const total = groups.reduce((sum, group) => sum + group.total, 0)
  const up = groups.reduce((sum, group) => sum + group.up_count, 0)
  if (total < MIN_FEEDBACK) return statsTexts.notEnoughFeedback
  return statsTexts.feedbackShare(formatShare(String(up / total)), total)
}

/** Сводка над очередью: плитки, распределение рекомендаций, оценки AI-заключений. */
export function StatsSummary() {
  const { data: stats } = useSuspenseQuery(managerStatsQuery())
  const byStatus = stats.applications_by_status
  const waitingClient = (byStatus.NEED_INFO ?? 0) + (byStatus.COUNTER_OFFER ?? 0)

  return (
    <section aria-labelledby="stats-title" className="grid gap-4">
      <h2 id="stats-title" className="sr-only">
        {statsTexts.title}
      </h2>
      <dl className="grid grid-cols-4 gap-4">
        <Tile label={statsTexts.underReview} value={String(byStatus.UNDER_REVIEW ?? 0)} />
        <Tile
          label={statsTexts.waitingClient}
          value={String(waitingClient)}
          hint={statsTexts.waitingClientHint}
        />
        <Tile
          label={statsTexts.medianTime}
          value={
            stats.median_time_to_decision_seconds === null
              ? statsTexts.noData
              : formatDuration(stats.median_time_to_decision_seconds)
          }
        />
        <Tile
          label={statsTexts.matching}
          value={
            stats.decisions_matching_suggestion_share === null
              ? statsTexts.noData
              : formatShare(stats.decisions_matching_suggestion_share)
          }
        />
      </dl>
      <div className="grid grid-cols-[2fr_1fr] gap-4">
        <Distribution stats={stats} />
        <Feedback groups={stats.ai_feedback_groups} />
      </div>
    </section>
  )
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="grid content-start gap-1 rounded-xl border bg-card p-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-3xl font-bold tabular-nums">{value}</dd>
      {hint && <dd className="text-xs text-muted-foreground">{hint}</dd>}
    </div>
  )
}

/** Одна серия — столбики одним цветом с подписью значения, легенда не нужна. */
function Distribution({ stats }: { stats: Stats }) {
  const values = SUGGESTED_ACTIONS.map((action) => ({
    action,
    count: stats.suggested_action_distribution[action] ?? 0,
  }))
  const max = Math.max(...values.map((item) => item.count))
  return (
    <div className="grid content-start gap-3 rounded-xl border bg-card p-4">
      <h3 className="text-sm font-medium text-muted-foreground">{statsTexts.distribution}</h3>
      {max === 0 ? (
        <p className="text-sm text-muted-foreground">{statsTexts.distributionEmpty}</p>
      ) : (
        <ul className="grid gap-2">
          {values.map(({ action, count }) => (
            <li key={action} className="grid grid-cols-[12rem_1fr_2rem] items-center gap-3">
              <span className="text-sm">{suggestedActionTexts[action].label}</span>
              <span className="h-3 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span
                  className="block h-full rounded-full bg-chart-1"
                  style={{ width: `${(count / max) * 100}%` }}
                />
              </span>
              <span className="text-right text-sm font-semibold tabular-nums">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Feedback({ groups }: { groups: FeedbackGroup[] }) {
  // Шаблонное заключение — отчёты при выключенной модели; остальное — ответы модели.
  const model = groups.filter((group) => group.source !== 'disabled')
  const template = groups.filter((group) => group.source === 'disabled')
  return (
    <div className="grid content-start gap-3 rounded-xl border bg-card p-4">
      <h3 className="text-sm font-medium text-muted-foreground">{statsTexts.feedback}</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
        <dt>{statsTexts.feedbackModel}</dt>
        <dd className="font-semibold">{feedbackShare(model)}</dd>
        <dt>{statsTexts.feedbackTemplate}</dt>
        <dd className="font-semibold">{feedbackShare(template)}</dd>
      </dl>
    </div>
  )
}
