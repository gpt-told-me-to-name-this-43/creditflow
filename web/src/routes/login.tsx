import { createFileRoute, redirect } from '@tanstack/react-router'
import { z } from 'zod'
import { LoginForm } from '@/features/auth/login-form.tsx'
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

function LoginPage() {
  return (
    <section className="grid gap-8">
      <div className="grid gap-2">
        <h1 className="text-3xl font-bold">Вход в кабинет</h1>
        <p className="text-muted-foreground">
          Войдите, чтобы подать заявку на кредит для бизнеса или узнать, что с текущей
        </p>
      </div>
      <LoginForm />
    </section>
  )
}
