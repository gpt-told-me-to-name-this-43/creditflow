import { useSuspenseQuery } from '@tanstack/react-query'
import { contractQuery } from '@/api/queries/applications.ts'
import { Badge } from '@/components/ui/badge.tsx'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card.tsx'
import { GlossaryTerm } from '@/components/ui/glossary-term.tsx'
import { PlainMarkdown } from '@/components/ui/plain-markdown.tsx'
import { glossary } from '@/content/glossary.ts'
import { contractTexts, scheduleTexts } from '@/content/contract.ts'
import { formatDate } from '@/lib/dates.ts'
import { formatMoney, formatRate } from '@/lib/money.ts'
import { ScheduleTable } from './schedule-table.tsx'

/** Договор: условия, ключевые положения (раскрываются) и график платежей. */
export function ContractSection({ applicationId }: { applicationId: string }) {
  const { data: contract } = useSuspenseQuery(contractQuery(applicationId))
  const status =
    contract.status === 'ISSUED' && contract.issued_at
      ? contractTexts.statusIssued(formatDate(contract.issued_at))
      : contract.status !== 'DRAFT' && contract.signed_at
        ? contractTexts.statusSigned(formatDate(contract.signed_at))
        : contractTexts.statusDraft

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-center justify-between gap-3">
        <CardTitle className="text-xl">{contractTexts.title(contract.number)}</CardTitle>
        <Badge variant={contract.status === 'DRAFT' ? 'outline' : 'success'}>{status}</Badge>
      </CardHeader>
      <CardContent className="grid gap-8">
        <dl className="grid grid-cols-3 gap-6">
          <Term label={contractTexts.amount} value={formatMoney(contract.amount_rub)} strong />
          <Term label={contractTexts.term} value={contractTexts.months(contract.term_months)} />
          <Term label={contractTexts.rate} value={formatRate(contract.annual_rate_pct)} />
          <Term
            label={contractTexts.payment}
            hint={glossary.monthlyPayment.text}
            value={formatMoney(contract.monthly_payment_rub)}
            strong
          />
          <Term
            label={contractTexts.overpayment}
            hint={glossary.overpayment.text}
            value={formatMoney(contract.overpayment_rub)}
          />
          <Term label={contractTexts.account} value={contract.account_masked} />
        </dl>

        <details className="group rounded-lg border p-4">
          <summary className="cursor-pointer font-semibold outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
            {contractTexts.keyTerms}
          </summary>
          <div className="mt-3">
            <PlainMarkdown source={contract.key_terms_markdown} />
          </div>
        </details>

        <div className="grid gap-3">
          <h3 className="text-lg font-semibold">{scheduleTexts.title}</h3>
          <ScheduleTable schedule={contract.schedule} />
        </div>
      </CardContent>
    </Card>
  )
}

function Term({
  label,
  hint,
  value,
  strong,
}: {
  label: string
  hint?: string
  value: string
  strong?: boolean
}) {
  return (
    <div className="grid gap-1">
      <dt className="text-sm text-muted-foreground">
        {hint ? <GlossaryTerm label={label} hint={hint} /> : label}
      </dt>
      <dd className={strong ? 'text-xl font-bold' : 'text-lg'}>{value}</dd>
    </div>
  )
}
