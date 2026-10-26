import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeftIcon } from 'lucide-react'
import { managerApplicationQuery } from '@/api/queries/manager.ts'
import { cardTexts } from '@/content/manager.ts'
import { AiReport } from './ai-report.tsx'
import { Calculation } from './calculation.tsx'
import { ExternalChecks } from './checks.tsx'
import { CardHeaderBlock } from './header.tsx'
import { History } from './history.tsx'
import { ProposalBlock, ProposalSummary } from './proposal.tsx'
import { Statement } from './statement.tsx'

/**
 * Карточка заявки менеджера: слева данные и расчёт, справа закреплённая рекомендация.
 * Расчёт, рекомендация и решение разнесены по разным блокам — решение принимает менеджер.
 */
export function ManagerCard({ applicationId }: { applicationId: string }) {
  const { data: application } = useSuspenseQuery(managerApplicationQuery(applicationId))
  const { scoring } = application

  return (
    <section className="grid gap-6">
      <Link
        to="/manager"
        search={{ status: 'UNDER_REVIEW' }}
        className="flex items-center gap-2 justify-self-start text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftIcon aria-hidden className="size-4" />
        {cardTexts.back}
      </Link>

      <CardHeaderBlock application={application} />

      <div className="grid grid-cols-[minmax(0,1fr)_22rem] items-start gap-6">
        <div className="grid gap-6">
          {application.ai_report && (
            <AiReport applicationId={application.id} initial={application.ai_report} />
          )}
          <ExternalChecks
            sources={application.sources}
            proposal={application.proposal}
            scoring={scoring}
          />
          {scoring && <Statement scoring={scoring} />}
          {scoring && <Calculation scoring={scoring} />}
          {application.proposal && <ProposalBlock proposal={application.proposal} />}
          <History application={application} />
        </div>
        <aside className="sticky top-6">
          <ProposalSummary application={application} />
        </aside>
      </div>
    </section>
  )
}
