import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeftIcon } from 'lucide-react'
import { applicationQuery, contractQuery } from '@/api/queries/applications.ts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card.tsx'
import { StatusBadge } from '@/components/ui/status-badge.tsx'
import { applicationTexts, offerTexts } from '@/content/application.ts'
import { purposeTexts } from '@/content/purposes.ts'
import { statusTexts } from '@/content/statuses.ts'
import { formatDate } from '@/lib/dates.ts'
import { formatMoney, formatRate } from '@/lib/money.ts'
import { ContractSection } from '../contract/contract-section.tsx'
import { SignPanel } from '../contract/sign-panel.tsx'
import {
  ApprovedBlock,
  DeclinedBlock,
  InfoRequestBlock,
  IssuedBlock,
  OfferBlock,
  RejectedBlock,
  SignedBlock,
  UnderReviewBlock,
} from './status-blocks.tsx'
import { Timeline } from './timeline.tsx'
import { useStatusChange } from './use-status-change.ts'

type Application = ReturnType<typeof useApplication>

function useApplication(applicationId: string) {
  return useSuspenseQuery(applicationQuery(applicationId)).data
}

/**
 * Страница заявки: статус и «что дальше», блок под статус, договор и подписание,
 * история. Данные обновляются опросом (lib/polling), кнопки — по `allowed_actions`.
 */
export function ApplicationPage({ applicationId }: { applicationId: string }) {
  const application = useApplication(applicationId)
  useStatusChange(applicationId, application.status)
  const status = statusTexts[application.status]
  const hasContract = application.allowed_actions.includes('VIEW_CONTRACT')

  return (
    <section className="grid gap-8">
      <Link
        to="/client"
        className="flex items-center gap-2 justify-self-start text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftIcon aria-hidden className="size-4" />
        {applicationTexts.backToList}
      </Link>

      <header className="grid gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <h1 className="text-3xl font-bold">
            {application.purpose_code
              ? purposeTexts[application.purpose_code].label
              : applicationTexts.title}
          </h1>
          <StatusBadge status={application.status} />
        </div>
        <div aria-live="polite" className="grid gap-1">
          <p className="text-lg">{status.now}</p>
          <p className="text-muted-foreground">{status.next}</p>
        </div>
      </header>

      <div className="grid grid-cols-[minmax(0,1fr)_20rem] items-start gap-10">
        <div className="grid gap-6">
          <StatusBlock application={application} />
          {hasContract && <ContractSection applicationId={applicationId} />}
          {application.status === 'APPROVED' && <SignPanel application={application} />}
        </div>
        <aside className="grid gap-8">
          <RequestSummary application={application} />
          <Timeline events={application.timeline} />
        </aside>
      </div>
    </section>
  )
}

function StatusBlock({ application }: { application: Application }) {
  switch (application.status) {
    case 'UNDER_REVIEW':
      return <UnderReviewBlock application={application} />
    case 'NEED_INFO':
      return <InfoRequestBlock application={application} />
    case 'COUNTER_OFFER':
      return <OfferBlock application={application} />
    case 'APPROVED':
      return <ApprovedBlock />
    case 'REJECTED':
      return <RejectedBlock application={application} />
    case 'DECLINED':
      return <DeclinedBlock />
    case 'SIGNED':
      return <SignedBlock />
    case 'ISSUED':
      return <IssuedContract applicationId={application.id} />
    case 'DRAFT':
      return null
  }
}

function IssuedContract({ applicationId }: { applicationId: string }) {
  const { data: contract } = useSuspenseQuery(contractQuery(applicationId))
  return <IssuedBlock contract={contract} />
}

function RequestSummary({ application }: { application: Application }) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>{applicationTexts.requestTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3">
          {application.requested_amount_rub && (
            <Item
              label={offerTexts.rows.amount}
              value={formatMoney(application.requested_amount_rub, { kopecks: false })}
            />
          )}
          {application.term_months && (
            <Item label={offerTexts.rows.term} value={offerTexts.months(application.term_months)} />
          )}
          {application.annual_rate_pct && (
            <Item label={offerTexts.rows.rate} value={formatRate(application.annual_rate_pct)} />
          )}
          {application.monthly_payment_rub && (
            <Item
              label={offerTexts.rows.payment}
              value={formatMoney(application.monthly_payment_rub)}
            />
          )}
          {application.submitted_at && (
            <p className="text-sm text-muted-foreground">
              {applicationTexts.submittedAt(formatDate(application.submitted_at))}
            </p>
          )}
        </dl>
      </CardContent>
    </Card>
  )
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="font-semibold">{value}</dd>
    </div>
  )
}
