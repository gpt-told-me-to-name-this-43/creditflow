import { createFileRoute, redirect } from '@tanstack/react-router'
import { applicationQuery, contractQuery } from '@/api/queries/applications.ts'
import { ApplicationPage } from '@/features/application/application-page.tsx'

export const Route = createFileRoute('/_auth/client/applications/$applicationId')({
  loader: async ({ context: { queryClient }, params: { applicationId } }) => {
    const application = await queryClient.ensureQueryData(applicationQuery(applicationId))
    // Черновик продолжают в мастере.
    if (application.status === 'DRAFT') {
      throw redirect({ to: '/client/applications/new', search: { applicationId }, replace: true })
    }
    if (application.allowed_actions.includes('VIEW_CONTRACT')) {
      await queryClient.ensureQueryData(contractQuery(applicationId))
    }
  },
  component: ApplicationRoute,
})

function ApplicationRoute() {
  const { applicationId } = Route.useParams()
  return <ApplicationPage key={applicationId} applicationId={applicationId} />
}
