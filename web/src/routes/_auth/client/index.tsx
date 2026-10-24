import { useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { applicationsQuery } from '@/api/queries/applications.ts'
import { companyQuery } from '@/api/queries/company.ts'
import { ApplicationList, NewApplicationButton } from '@/features/application/application-list.tsx'

export const Route = createFileRoute('/_auth/client/')({
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(applicationsQuery()),
      queryClient.ensureQueryData(companyQuery()),
    ]),
  component: ClientHome,
})

function ClientHome() {
  const { data: company } = useSuspenseQuery(companyQuery())
  return (
    <section className="grid gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="text-3xl font-bold">Мои заявки</h1>
          <p className="text-muted-foreground">{company.name}</p>
        </div>
        <NewApplicationButton />
      </div>
      <ApplicationList />
    </section>
  )
}
