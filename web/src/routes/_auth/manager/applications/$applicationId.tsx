import { createFileRoute } from '@tanstack/react-router'
import { managerApplicationQuery } from '@/api/queries/manager.ts'
import { ManagerCard } from '@/features/manager/card/manager-card.tsx'

export const Route = createFileRoute('/_auth/manager/applications/$applicationId')({
  loader: ({ context: { queryClient }, params: { applicationId } }) =>
    queryClient.ensureQueryData(managerApplicationQuery(applicationId)),
  component: ManagerCardRoute,
})

function ManagerCardRoute() {
  const { applicationId } = Route.useParams()
  return <ManagerCard key={applicationId} applicationId={applicationId} />
}
