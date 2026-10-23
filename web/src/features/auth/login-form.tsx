import { useForm } from '@tanstack/react-form'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { z } from 'zod'
import { errorMessage } from '@/api/errors.ts'
import { demoAccountsQuery } from '@/api/queries/auth.ts'
import type { components } from '@/api/schema.d.ts'
import { Button } from '@/components/ui/button.tsx'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card.tsx'
import { firstError, FormField } from '@/components/ui/form-field.tsx'
import { Input } from '@/components/ui/input.tsx'
import { demoScenarioTexts, demoTexts } from '@/content/demo.ts'
import { signIn } from '@/lib/auth.ts'
import { logIn } from './log-in.ts'

type DemoAccount = components['schemas']['DemoAccount']

const schema = z.object({
  login: z.string().trim().min(1, 'Введите логин'),
  password: z.string().min(1, 'Введите пароль'),
})

export function LoginForm() {
  const router = useRouter()
  const queryClient = useQueryClient()
  // После входа гард /login сам уводит на redirect или в кабинет роли.
  const login = useMutation({
    mutationFn: logIn,
    meta: { errorToast: false },
    onSuccess: (session) => signIn(session, { router, queryClient }),
  })

  const form = useForm({
    defaultValues: { login: '', password: '' },
    validators: { onBlur: schema, onSubmit: schema },
    onSubmit: ({ value }) =>
      // Ошибку показывает login.error под формой.
      login
        .mutateAsync({ login: value.login.trim(), password: value.password })
        .catch(() => undefined),
  })

  const fillDemo = (account: DemoAccount) => {
    form.setFieldValue('login', account.login)
    form.setFieldValue('password', account.password)
    login.reset()
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,28rem)_minmax(0,1fr)]">
      <form
        noValidate
        className="grid content-start gap-5"
        onSubmit={(event) => {
          event.preventDefault()
          void form.handleSubmit()
        }}
      >
        <form.Field name="login">
          {(field) => (
            <FormField
              id="login"
              label="Логин"
              error={field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined}
            >
              {(props) => (
                <Input
                  {...props}
                  autoComplete="username"
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                  onBlur={field.handleBlur}
                />
              )}
            </FormField>
          )}
        </form.Field>
        <form.Field name="password">
          {(field) => (
            <FormField
              id="password"
              label="Пароль"
              error={field.state.meta.isTouched ? firstError(field.state.meta.errors) : undefined}
            >
              {(props) => (
                <Input
                  {...props}
                  type="password"
                  autoComplete="current-password"
                  value={field.state.value}
                  onChange={(event) => field.handleChange(event.target.value)}
                  onBlur={field.handleBlur}
                />
              )}
            </FormField>
          )}
        </form.Field>
        {login.isError && (
          <p role="alert" className="font-medium text-destructive">
            {errorMessage(login.error)}
          </p>
        )}
        <Button type="submit" size="lg" disabled={login.isPending}>
          {login.isPending ? 'Входим…' : 'Войти'}
        </Button>
      </form>
      <DemoAccounts onPick={fillDemo} />
    </div>
  )
}

/** Демо-учётки есть только при DEMO_AUTH_ENABLED: при ошибке блок просто не показываем. */
function DemoAccounts({ onPick }: { onPick: (account: DemoAccount) => void }) {
  const { data: accounts } = useQuery({ ...demoAccountsQuery(), retry: false })
  if (!accounts?.length) return null
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>{demoTexts.title}</CardTitle>
        <CardDescription>{demoTexts.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-2 sm:grid-cols-2">
          {accounts.map((account) => (
            <li key={account.login}>
              <button
                type="button"
                onClick={() => onPick(account)}
                className="grid w-full gap-0.5 rounded-lg border px-4 py-3 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <span className="font-semibold">{account.label}</span>
                <span className="text-sm text-muted-foreground">
                  {demoScenarioTexts[account.scenario] ?? account.scenario}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
