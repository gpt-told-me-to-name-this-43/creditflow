import type { Mutation, QueryClient } from '@tanstack/react-query'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { toast } from 'sonner'
import { describe, expect, it, vi } from 'vitest'
import { StaleSessionError } from '@/api/errors.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import { networkErrorMessage } from '@/content/errors.ts'
import { logIn } from '@/features/auth/log-in.ts'
import { signIn, signOut } from '@/lib/auth.ts'
import { bindCompany, DEMO_PASSWORD } from '@/mocks/db.ts'
import { renderApp } from '@/test/render.tsx'
import { server } from '@/test/server.ts'
import { demoUser, signInAs, signInWithCompany } from '@/test/session.ts'

function deferred() {
  let resolve: () => void = () => {}
  const promise = new Promise<void>((done) => (resolve = done))
  return { promise, resolve }
}

/** Запрос ждёт `release()` и затем уходит в настоящий мок; `arrived` — запрос дошёл. */
function holdRequest(method: 'post', path: string) {
  const arrived = deferred()
  const gate = deferred()
  server.use(
    http[method](`*/api/v1${path}`, async () => {
      arrived.resolve()
      await gate.promise
    }),
  )
  return { arrived: arrived.promise, release: gate.resolve }
}

/**
 * Ответ с заголовками сразу и телом по команде. `reading` — клиент начал читать тело, то есть
 * onResponse уже отработал: без буфера (highWaterMark 0) pull вызывается только при чтении.
 */
function holdBody(method: 'post' | 'patch', path: string, body: unknown) {
  const reading = deferred()
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined
  server.use(
    http[method](`*/api/v1${path}`, () => {
      const stream = new ReadableStream<Uint8Array>(
        { start: (c) => void (controller = c), pull: () => reading.resolve() },
        { highWaterMark: 0 },
      )
      return new HttpResponse(stream, { headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return {
    reading: reading.promise,
    finish() {
      controller?.enqueue(new TextEncoder().encode(JSON.stringify(body)))
      controller?.close()
    },
    fail: () => controller?.error(new TypeError('terminated')),
  }
}

/** Единственная мутация в пути — её запомним до выхода: clear() убирает её из кэша. */
function pendingMutation(queryClient: QueryClient) {
  const pending = queryClient
    .getMutationCache()
    .getAll()
    .filter((mutation) => mutation.state.status === 'pending')
  expect(pending).toHaveLength(1)
  return pending[0] as Mutation<unknown, Error, unknown, unknown>
}

/** Статус мутации меняется после всех её onSuccess/onError — обработка ответа закончена. */
async function settled(mutation: Mutation<unknown, Error, unknown, unknown>) {
  await vi.waitFor(() => expect(mutation.state.status).not.toBe('pending'))
  return mutation.state
}

async function switchToTechservice(
  app: Pick<ReturnType<typeof renderApp>, 'router' | 'queryClient'>,
) {
  await signOut(app)
  // B входит с экрана входа, а не с адреса прошлого пользователя (там его 404).
  await app.router.navigate({ to: '/login' })
  const next = demoUser('director.techservice')
  bindCompany(next.id, '0099010012')
  const session = await logIn({ login: next.email, password: DEMO_PASSWORD })
  await signIn(session, app)
  await screen.findByRole('heading', { name: 'Мои заявки' })
}

const cachedData = (queryClient: QueryClient) =>
  JSON.stringify(
    queryClient
      .getQueryCache()
      .getAll()
      .map((query) => query.state.data),
  )

async function startBinding() {
  await signInAs('director.bakery')
  const user = userEvent.setup()
  const app = renderApp('/client/onboarding')
  await screen.findByRole('heading', { name: 'Подключите компанию' })
  return {
    ...app,
    submit: async () => {
      await user.type(screen.getByLabelText('ИНН компании или ИП'), '0099020010')
      await user.click(screen.getByRole('checkbox'))
      await user.click(screen.getByRole('button', { name: 'Найти компанию' }))
    },
  }
}

describe('изоляция сессий', () => {
  it('поздний ответ мутации прошлого пользователя не попадает в кэш новой сессии', async () => {
    const { router, queryClient, submit } = await startBinding()
    const held = holdRequest('post', '/onboarding/company-binding')
    await submit()
    await held.arrived
    const binding = pendingMutation(queryClient)

    // Выход и вход другим клиентом, пока привязка первого ещё в пути.
    await switchToTechservice({ router, queryClient })
    const companyOfNext = queryClient.getQueryData(queryKeys.company)

    held.release()
    expect((await settled(binding)).error).toBeInstanceOf(StaleSessionError)

    expect(queryClient.getQueryData(queryKeys.company)).toEqual(companyOfNext)
    expect(cachedData(queryClient)).not.toContain('Пекарня')
    expect(router.state.location.pathname).toBe('/client')
    expect(screen.queryByText('Мы нашли вашу компанию')).not.toBeInTheDocument()
  })

  it('тело ответа привязки дочитывается после смены пользователя — кэш новой сессии чист', async () => {
    const { router, queryClient, submit } = await startBinding()
    const held = holdBody('post', '/onboarding/company-binding', { name: 'ООО «Пекарня Плюс»' })
    await submit()
    await held.reading
    const binding = pendingMutation(queryClient)

    await switchToTechservice({ router, queryClient })

    held.finish()
    expect((await settled(binding)).error).toBeInstanceOf(StaleSessionError)
    expect(cachedData(queryClient)).not.toContain('Пекарня')
    expect(router.state.location.pathname).toBe('/client')
  })

  it('обрыв тела ответа прошлого пользователя не показывает ошибку новому', async () => {
    await signInWithCompany('director.bakery', '0099020010')
    const user = userEvent.setup()
    const { router, queryClient } = renderApp('/client/applications/new')
    await screen.findByRole('heading', { name: 'Расскажите, на что нужны деньги' })
    const errorToast = vi.spyOn(toast, 'error')

    // Сохранение шага 1 мастера: тост об ошибке — общий для всех экранов.
    const held = holdBody('patch', '/applications/:application_id', {})
    await user.type(screen.getByLabelText('Что нужно бизнесу'), 'Новая печь')
    await user.click(screen.getByRole('button', { name: 'Дальше' }))
    await held.reading
    const save = pendingMutation(queryClient)

    await switchToTechservice({ router, queryClient })

    held.fail()
    expect((await settled(save)).error).toBeInstanceOf(StaleSessionError)
    expect(errorToast).not.toHaveBeenCalled()
    expect(screen.queryByText(networkErrorMessage)).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/client')
  })
})
