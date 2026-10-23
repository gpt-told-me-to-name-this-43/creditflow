import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { applicationsQuery } from '@/api/queries/applications.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { Card } from '@/components/ui/card.tsx'
import { EmptyState } from '@/components/ui/empty-state.tsx'
import { StatusBadge } from '@/components/ui/status-badge.tsx'
import { purposeTexts } from '@/content/purposes.ts'
import { statusTexts } from '@/content/statuses.ts'
import { formatDate } from '@/lib/dates.ts'
import { formatMoney } from '@/lib/money.ts'

type Application = components['schemas']['ClientApplicationView']

export function NewApplicationButton() {
  return (
    <Button asChild size="lg">
      <Link to="/client/applications/new">Подать заявку</Link>
    </Button>
  )
}

export function ApplicationList() {
  const { data: applications } = useSuspenseQuery(applicationsQuery())

  if (applications.length === 0) {
    return (
      <EmptyState
        title="Заявок пока нет"
        description="Расскажите своими словами, на что нужны деньги, — мы подберём подходящий кредит"
        action={<NewApplicationButton />}
      />
    )
  }

  return (
    <ul className="grid gap-4" aria-label="Заявки">
      {applications.map((application) => (
        <li key={application.id}>
          <ApplicationCard application={application} />
        </li>
      ))}
    </ul>
  )
}

function terms(application: Application) {
  const parts = []
  if (application.requested_amount_rub) {
    parts.push(formatMoney(application.requested_amount_rub, { kopecks: false }))
  }
  if (application.term_months) parts.push(`на ${application.term_months} мес.`)
  return parts.join(' ')
}

function ApplicationCard({ application }: { application: Application }) {
  const status = statusTexts[application.status]
  const purpose = application.purpose_code && purposeTexts[application.purpose_code].label
  const isDraft = application.status === 'DRAFT'
  return (
    <Card className="flex-row items-center justify-between gap-6 px-6">
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">{purpose ?? 'Цель пока не указана'}</h2>
          <StatusBadge status={application.status} />
        </div>
        {terms(application) && <p className="text-lg">{terms(application)}</p>}
        <p className="text-muted-foreground">
          {status.now}. {status.next}
        </p>
        {application.submitted_at && (
          <p className="text-sm text-muted-foreground">
            Отправлена {formatDate(application.submitted_at)}
          </p>
        )}
      </div>
      <Button asChild variant={isDraft ? 'default' : 'outline'} className="shrink-0">
        {isDraft ? (
          <Link to="/client/applications/new" search={{ applicationId: application.id }}>
            Продолжить
          </Link>
        ) : (
          <Link to="/client/applications/$applicationId" params={{ applicationId: application.id }}>
            Подробнее
          </Link>
        )}
      </Button>
    </Card>
  )
}
