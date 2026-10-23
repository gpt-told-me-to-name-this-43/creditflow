import { createFileRoute, redirect } from '@tanstack/react-router'
import { z } from 'zod'
import { homeFor } from '@/lib/auth.ts'

const searchSchema = z.object({
  // Только внутренний путь: «//host» и абсолютные URL отбрасываем, чтобы не было open redirect.
  redirect: z
    .string()
    .regex(/^\/(?!\/)/)
    .optional()
    .catch(undefined),
})

export const Route = createFileRoute('/login')({
  validateSearch: searchSchema,
  beforeLoad: ({ context, search }) => {
    const session = context.auth.getSession()
    if (session) throw redirect({ to: search.redirect ?? homeFor(session.role) })
  },
  component: LoginPage,
})

// Форма входа и демо-доступ — фаза 4 плана, когда в контракте появится /auth/login.
function LoginPage() {
  return (
    <section className="mx-auto max-w-md">
      <h1 className="text-3xl font-bold">Вход в кабинет</h1>
    </section>
  )
}
