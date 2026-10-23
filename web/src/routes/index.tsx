import { createFileRoute, redirect } from '@tanstack/react-router'
import { homeFor } from '@/lib/auth.ts'

// Корень — только развилка: в кабинет по роли или на вход.
export const Route = createFileRoute('/')({
  beforeLoad: ({ context }) => {
    const session = context.auth.getSession()
    throw redirect({ to: session ? homeFor(session.role) : '/login' })
  },
})
