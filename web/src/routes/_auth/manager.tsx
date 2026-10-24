import { createFileRoute, redirect } from '@tanstack/react-router'
import { homeFor } from '@/lib/auth.ts'

// Экраны кабинета менеджера — #10.
export const Route = createFileRoute('/_auth/manager')({
  beforeLoad: ({ context }) => {
    if (context.session.role !== 'MANAGER') throw redirect({ to: homeFor(context.session.role) })
  },
})
