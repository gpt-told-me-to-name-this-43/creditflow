import { createFileRoute, redirect } from '@tanstack/react-router'
import { homeFor } from '@/lib/auth.ts'

export const Route = createFileRoute('/_auth/client')({
  beforeLoad: ({ context }) => {
    if (context.session.role !== 'CLIENT') throw redirect({ to: homeFor(context.session.role) })
    // Нет привязанной компании → /client/onboarding: проверка по GET /company появится
    // вместе с экраном привязки (фаза 4), когда эндпоинт будет в контракте.
  },
})
