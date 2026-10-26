import type { ReactNode } from 'react'
import type { components } from '@/api/schema.d.ts'
import { Badge } from '@/components/ui/badge.tsx'
import { cardTexts, historyTexts, managerActionTexts } from '@/content/manager.ts'
import { reasonTexts } from '@/content/reasons.ts'
import { statusTexts } from '@/content/statuses.ts'
import { formatDateTime } from '@/lib/dates.ts'
import { formatMoney, formatRate } from '@/lib/money.ts'

type Application = components['schemas']['ManagerApplicationView']

/** История заявки: решения, вопросы, предложения, договор и смена статусов. */
export function History({ application }: { application: Application }) {
  const { decisions, info_requests, offers, contract, sign_challenges, timeline } = application
  return (
    <section aria-labelledby="history-title" className="grid gap-6 rounded-xl border bg-card p-6">
      <h2 id="history-title" className="text-xl font-semibold">
        {cardTexts.history}
      </h2>

      <Part title={cardTexts.decisions}>
        {decisions.length === 0 ? (
          <p className="text-sm text-muted-foreground">{cardTexts.noDecisions}</p>
        ) : (
          <ul className="grid gap-3">
            {decisions.map((decision) => (
              <li key={decision.id} className="grid gap-1 rounded-lg border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{managerActionTexts[decision.action]}</span>
                  <span className="text-sm text-muted-foreground">
                    {formatDateTime(decision.created_at)}{' '}
                    {historyTexts.by(decision.manager_full_name)}
                  </span>
                </div>
                {decision.client_reason_code && (
                  <p className="text-sm">
                    <span className="text-muted-foreground">{cardTexts.clientReason}: </span>
                    {reasonTexts[decision.client_reason_code].reason}
                  </p>
                )}
                {decision.comment && (
                  <p className="text-sm whitespace-pre-line">
                    <span className="text-muted-foreground">{cardTexts.comment}: </span>
                    {decision.comment}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Part>

      {info_requests.length > 0 && (
        <Part title={cardTexts.questions}>
          <ul className="grid gap-3">
            {info_requests.map((item) => (
              <li key={item.id} className="grid gap-2 rounded-lg border p-4">
                <p className="font-medium whitespace-pre-line">{item.question_text}</p>
                <p className="text-xs text-muted-foreground">{formatDateTime(item.created_at)}</p>
                <div className="grid gap-1 border-t pt-2">
                  <span className="text-sm text-muted-foreground">{cardTexts.answer}</span>
                  {item.answer_text ? (
                    <>
                      <p className="whitespace-pre-line">{item.answer_text}</p>
                      {item.answered_at && (
                        <p className="text-xs text-muted-foreground">
                          {formatDateTime(item.answered_at)}
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">{cardTexts.noAnswer}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Part>
      )}

      {offers.length > 0 && (
        <Part title={cardTexts.offers}>
          <ul className="grid gap-3">
            {offers.map((offer) => (
              <li key={offer.id} className="grid gap-2 rounded-lg border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold tabular-nums">
                    {formatMoney(offer.amount_rub, { kopecks: false })} ·{' '}
                    {cardTexts.months(offer.term_months)}
                  </span>
                  <Badge variant={offer.status === 'ACCEPTED' ? 'success' : 'outline'}>
                    {cardTexts.offerStatus[offer.status]}
                  </Badge>
                </div>
                <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                  <Fact
                    label={historyTexts.payment}
                    value={formatMoney(offer.monthly_payment_rub)}
                  />
                  <Fact
                    label={historyTexts.overpayment}
                    value={formatMoney(offer.overpayment_rub)}
                  />
                  <Fact label={historyTexts.rate} value={formatRate(offer.annual_rate_pct)} />
                  <Fact label={cardTexts.dscr} value={offer.scoring.dscr ?? '—'} />
                </dl>
                <p className="text-xs text-muted-foreground">{formatDateTime(offer.created_at)}</p>
              </li>
            ))}
          </ul>
        </Part>
      )}

      {contract && (
        <Part title={cardTexts.signing}>
          <div className="grid gap-2 rounded-lg border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{historyTexts.contract(contract.number)}</span>
              <Badge variant={contract.status === 'ISSUED' ? 'success' : 'outline'}>
                {historyTexts.contractStatus[contract.status]}
              </Badge>
            </div>
            <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <Fact
                label={cardTexts.amount}
                value={formatMoney(contract.amount_rub, { kopecks: false })}
              />
              <Fact label={cardTexts.term} value={cardTexts.months(contract.term_months)} />
              <Fact
                label={historyTexts.payment}
                value={formatMoney(contract.monthly_payment_rub)}
              />
              <Fact label={historyTexts.account} value={contract.account_masked} />
              {contract.signed_at && (
                <Fact label={historyTexts.signedAt} value={formatDateTime(contract.signed_at)} />
              )}
              {contract.issued_at && (
                <Fact label={historyTexts.issuedAt} value={formatDateTime(contract.issued_at)} />
              )}
            </dl>
            {sign_challenges.length > 0 && (
              <ul className="grid gap-1 border-t pt-2 text-sm">
                {sign_challenges.map((challenge) => (
                  <li key={challenge.id} className="text-muted-foreground">
                    {formatDateTime(challenge.created_at)} ·{' '}
                    {cardTexts.challenge(challenge.attempts)} ·{' '}
                    {challenge.used_at ? historyTexts.challengeUsed : historyTexts.challengeOpen}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Part>
      )}

      <Part title={cardTexts.events}>
        <ol className="grid gap-2 border-l pl-4">
          {timeline.map((event) => (
            <li key={event.id} className="grid gap-0.5">
              <span className="font-medium">
                {event.from_status
                  ? historyTexts.statusChange(
                      statusTexts[event.from_status].label,
                      statusTexts[event.to_status].label,
                    )
                  : historyTexts.created}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatDateTime(event.created_at)}{' '}
                {historyTexts.by(event.actor_full_name ?? cardTexts.system)}
              </span>
            </li>
          ))}
        </ol>
      </Part>
    </section>
  )
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid gap-3">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      {children}
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  )
}
