import { createFileRoute, redirect } from '@tanstack/react-router'
import { meQuery } from '@/api/queries/auth.ts'
import { homeFor } from '@/lib/auth.ts'

const ONBOARDING = '/client/onboarding'

// Кабинет клиента: без привязанной компании доступна только привязка,
// с компанией привязка уже не нужна (company_id — из GET /auth/me).
export const Route = createFileRoute('/_auth/client')({
  beforeLoad: async ({ context, location }) => {
    if (context.session.role !== 'CLIENT') throw redirect({ to: homeFor(context.session.role) })
    const me = await context.queryClient.ensureQueryData(meQuery())
    const onOnboarding = location.pathname === ONBOARDING
    if (!me.company_id && !onOnboarding) throw redirect({ to: ONBOARDING })
    if (me.company_id && onOnboarding) throw redirect({ to: '/client' })
  },
})
