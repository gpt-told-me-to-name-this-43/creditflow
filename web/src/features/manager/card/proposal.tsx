import { CheckIcon, MinusIcon, OctagonAlertIcon } from 'lucide-react'
import type { components } from '@/api/schema.d.ts'
import { cardTexts, ruleTexts, stopFactorTexts, suggestedActionTexts } from '@/content/manager.ts'
import { cn } from '@/lib/utils.ts'
import { SuggestionBadge } from '../suggestion-badge.tsx'
import { DecisionPanel, type DecisionRequest } from './decision.tsx'

type Schemas = components['schemas']
type Application = Schemas['ManagerApplicationView']

/** Как DecisionPolicy пришла к рекомендации: все правила, первое сработавшее выделено. */
export function ProposalBlock({ proposal }: { proposal: Schemas['Proposal'] }) {
  const first = proposal.rule_trace.find((item) => item.matched)?.rule
  return (
    <section aria-labelledby="proposal-title" className="grid gap-4 rounded-xl border bg-card p-6">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="proposal-title" className="text-xl font-semibold">
          {cardTexts.ruleTrace}
        </h2>
        <span className="text-xs text-muted-foreground">{proposal.policy_version}</span>
      </div>
      <table className="w-full text-left text-sm">
        <thead className="text-muted-foreground">
          <tr className="border-b">
            <th className="py-2 font-medium">{cardTexts.rule}</th>
            <th className="py-2 font-medium">{cardTexts.matched}</th>
            <th className="py-2 font-medium">{cardTexts.why}</th>
          </tr>
        </thead>
        <tbody>
          {proposal.rule_trace.map((item) => (
            <tr
              key={item.rule}
              className={cn(
                'border-b last:border-0',
                item.rule === first && 'bg-muted font-semibold',
              )}
            >
              <td className="py-2 pr-4">
                {ruleTexts[item.rule]}
                {item.rule === first && (
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    ({cardTexts.first})
                  </span>
                )}
              </td>
              <td className="py-2 pr-4">
                <span className="flex items-center gap-1">
                  {item.matched ? (
                    <CheckIcon aria-hidden className="size-4" />
                  ) : (
                    <MinusIcon aria-hidden className="size-4 text-muted-foreground" />
                  )}
                  {item.matched ? cardTexts.yes : cardTexts.no}
                </span>
              </td>
              <td className="py-2 font-normal text-muted-foreground">{item.detail ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/** Закреплённая справа сводка: рекомендация, стоп-факторы и доступные решения. */
export function ProposalSummary({
  application,
  request,
  onRequest,
}: {
  application: Application
  request: DecisionRequest | null
  onRequest: (request: DecisionRequest | null) => void
}) {
  const { proposal } = application
  return (
    <section aria-labelledby="summary-title" className="grid gap-5 rounded-xl border bg-card p-6">
      <div className="grid gap-2">
        <h2 id="summary-title" className="text-sm font-medium text-muted-foreground">
          {cardTexts.suggestion}
        </h2>
        {proposal ? (
          <>
            <SuggestionBadge action={proposal.suggested_action} />
            <p className="text-sm">{suggestedActionTexts[proposal.suggested_action].description}</p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{cardTexts.noProposal}</p>
        )}
      </div>

      {proposal && proposal.blocking_codes.length > 0 && (
        <div className="grid gap-2">
          <h3 className="text-sm font-medium text-muted-foreground">{cardTexts.blocking}</h3>
          <ul className="grid gap-2">
            {proposal.blocking_codes.map((code) => (
              <li key={code} className="flex gap-2 text-sm font-medium text-destructive">
                <OctagonAlertIcon aria-hidden className="size-4 shrink-0 translate-y-0.5" />
                {stopFactorTexts[code]}
              </li>
            ))}
          </ul>
        </div>
      )}

      <DecisionPanel application={application} request={request} onRequest={onRequest} />
    </section>
  )
}
