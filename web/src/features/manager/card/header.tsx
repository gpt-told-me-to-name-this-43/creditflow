import type { components } from '@/api/schema.d.ts'
import { StatusBadge } from '@/components/ui/status-badge.tsx'
import {
  cardTexts,
  fieldSourceTexts,
  legalFormTexts,
  productName,
  termsSourceManagerTexts,
} from '@/content/manager.ts'
import { purposeTexts } from '@/content/purposes.ts'
import { formatDate, formatDateTime } from '@/lib/dates.ts'
import { formatMoney } from '@/lib/money.ts'

type Application = components['schemas']['ManagerApplicationView']

/** Подпись источника поля: «Сумма — правила». Ручные поля без подписи. */
function SourceNote({ application, field }: { application: Application; field: string }) {
  const source = application.terms_field_sources[field]
  if (!source || source === 'MANUAL') return null
  return <span className="text-xs text-muted-foreground"> · {fieldSourceTexts[source]}</span>
}

export function CardHeaderBlock({ application }: { application: Application }) {
  return (
    <header className="grid gap-4 rounded-xl border bg-card p-6">
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-3xl font-bold">{application.company_name}</h1>
        <StatusBadge status={application.status} />
      </div>
      <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <Fact label={cardTexts.inn} value={application.company_inn} />
        <Fact label={cardTexts.legalForm} value={legalFormTexts[application.legal_form]} />
        <Fact label={cardTexts.okved} value={application.okved_main} />
        <Fact label={cardTexts.registered} value={formatDate(application.registered_at)} />
        {application.submitted_at && (
          <Fact label={cardTexts.submitted} value={formatDateTime(application.submitted_at)} />
        )}
      </dl>

      <div className="grid gap-3 border-t pt-4">
        <h2 className="text-sm font-medium text-muted-foreground">{cardTexts.request}</h2>
        <dl className="grid grid-cols-5 gap-4">
          <div className="grid gap-0.5">
            <dt className="text-sm text-muted-foreground">{cardTexts.purpose}</dt>
            <dd className="font-semibold">
              {application.purpose_code ? purposeTexts[application.purpose_code].label : '—'}
              <SourceNote application={application} field="purpose_code" />
            </dd>
          </div>
          <div className="grid gap-0.5">
            <dt className="text-sm text-muted-foreground">{cardTexts.amount}</dt>
            <dd className="font-semibold tabular-nums">
              {application.requested_amount_rub
                ? formatMoney(application.requested_amount_rub, { kopecks: false })
                : '—'}
              <SourceNote application={application} field="requested_amount_rub" />
            </dd>
          </div>
          <div className="grid gap-0.5">
            <dt className="text-sm text-muted-foreground">{cardTexts.term}</dt>
            <dd className="font-semibold">
              {application.term_months ? cardTexts.months(application.term_months) : '—'}
              <SourceNote application={application} field="term_months" />
            </dd>
          </div>
          <div className="grid gap-0.5">
            <dt className="text-sm text-muted-foreground">{cardTexts.product}</dt>
            <dd className="font-semibold">{productName(application.product_id)}</dd>
          </div>
          <div className="grid gap-0.5">
            <dt className="text-sm text-muted-foreground">{cardTexts.termsSource}</dt>
            <dd className="font-semibold">{termsSourceManagerTexts[application.terms_source]}</dd>
          </div>
        </dl>
        {application.purpose_text && (
          <p className="text-sm">
            <span className="text-muted-foreground">{cardTexts.purposeText}: </span>«
            {application.purpose_text}»
          </p>
        )}
      </div>
    </header>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  )
}
