import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, onTestFinished } from 'vitest'
import { useSaveDraft } from '@/features/wizard/wizard-form.ts'
import { auth } from '@/lib/auth.ts'
import { createQueryClient } from '@/lib/query-client.ts'
import { db } from '@/mocks/db.ts'
import { toClientView } from '@/mocks/views.ts'
import { server } from '@/test/server.ts'
import { signInWithCompany } from '@/test/session.ts'
import {
  applicationQuery,
  markSession,
  type SessionMark,
  storeApplication,
} from './applications.ts'

function deferred() {
  let resolve: () => void = () => {}
  const promise = new Promise<void>((done) => (resolve = done))
  return { promise, resolve }
}

/**
 * Реальная последовательность: PATCH отвечает revision 2 → пока ответ идёт, заявка
 * на бэке меняется ещё раз → MutationCache инвалидирует карточку, refetch приносит
 * revision 3 → только потом выполняется локальный onSuccess мутации.
 */
async function setup() {
  const client = await signInWithCompany('director.techservice', '0099010012')
  const row = db.createApplication(client)
  let current = { ...toClientView(row), revision: 1 }
  let patched = false
  let onRefetch = () => {}
  server.use(
    http.get('*/api/v1/applications/:applicationId', () => {
      if (patched) onRefetch()
      return HttpResponse.json(current)
    }),
    http.patch('*/api/v1/applications/:applicationId', () => {
      const response = { ...current, revision: 2, purpose_text: 'ответ PATCH' }
      current = { ...current, revision: 3, purpose_text: 'свежий снимок' }
      patched = true
      return HttpResponse.json(response)
    }),
  )
  const queryClient = createQueryClient({ onUnauthorized: () => {} })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  const { result } = renderHook(
    () => ({ detail: useQuery(applicationQuery(row.id)), save: useSaveDraft(row.id) }),
    { wrapper },
  )
  await waitFor(() => expect(result.current.detail.data?.revision).toBe(1))
  return {
    queryClient,
    result,
    key: applicationQuery(row.id).queryKey,
    duringRefetch: (fn: () => void) => (onRefetch = fn),
  }
}

describe('кэш карточки заявки после мутации', () => {
  it('ответ мутации (revision 2) не перезаписывает refetch (revision 3)', async () => {
    const { queryClient, result, key } = await setup()
    await result.current.save.mutateAsync({ purpose_text: 'текст' })
    expect(queryClient.getQueryData(key)).toMatchObject({
      revision: 3,
      purpose_text: 'свежий снимок',
    })
  })

  it('сессия сменилась, пока шёл refetch, — ответ мутации в кэш не пишется', async () => {
    const { queryClient, result, key, duringRefetch } = await setup()
    // Ответ PATCH пришёл в своей сессии; выход случился, пока MutationCache ждёт refetch.
    duringRefetch(() => {
      auth.clear()
      queryClient.clear()
    })
    await result.current.save.mutateAsync({ purpose_text: 'текст' }).catch(() => undefined)
    expect(queryClient.getQueryData(key)).toBeUndefined()
  })

  it('запоздавший GET (revision 2) не откатывает уже записанную revision 3', async () => {
    const client = await signInWithCompany('director.techservice', '0099010012')
    const row = db.createApplication(client)
    const view = toClientView(row)
    let releaseOld = () => {}
    const oldArrives = new Promise<void>((resolve) => (releaseOld = resolve))
    let started = () => {}
    const fetchStarted = new Promise<void>((resolve) => (started = resolve))
    server.use(
      http.get('*/api/v1/applications/:applicationId', async () => {
        started()
        await oldArrives
        return HttpResponse.json({ ...view, revision: 2, purpose_text: 'старый GET' })
      }),
    )
    const queryClient = createQueryClient({ onUnauthorized: () => {} })
    const { queryKey } = applicationQuery(row.id)
    const pending = queryClient.fetchQuery(applicationQuery(row.id))
    await fetchStarted
    storeApplication(
      queryClient,
      { ...view, revision: 3, purpose_text: 'ответ мутации' },
      markSession(),
    )
    releaseOld()
    await pending
    expect(queryClient.getQueryData(queryKey)).toMatchObject({
      revision: 3,
      purpose_text: 'ответ мутации',
    })
  })

  it.each([
    ['карточка на экране', true],
    ['карточка только в кэше (лоадер), инвалидация не отменяет опрос', false],
  ])('опрос с revision 1 приходит после записи ответа мутации — %s', async (_, observed) => {
    const client = await signInWithCompany('director.techservice', '0099010012')
    const row = db.createApplication(client)
    let current = { ...toClientView(row), revision: 1, purpose_text: 'исходный' }
    const { queryKey } = applicationQuery(row.id)
    const pollStarted = deferred()
    const releasePoll = deferred()
    const pollAnswered = deferred()
    let gets = 0
    server.use(
      http.get('*/api/v1/applications/:applicationId', async () => {
        gets += 1
        if (gets !== 2) return HttpResponse.json(current)
        // Второй GET — опрос: снимок до PATCH, ответ — только по команде теста.
        const snapshot = current
        pollStarted.resolve()
        await releasePoll.promise
        return HttpResponse.json(snapshot)
      }),
      http.patch('*/api/v1/applications/:applicationId', () => {
        current = { ...current, revision: 2, purpose_text: 'ответ PATCH' }
        return HttpResponse.json(current)
      }),
    )
    server.events.on('response:mocked', () => {
      if (gets === 2) pollAnswered.resolve()
    })
    onTestFinished(() => server.events.removeAllListeners())

    const queryClient = createQueryClient({ onUnauthorized: () => {} })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    // Без наблюдателя карточка как после лоадера: в кэше, но не активна.
    const useDetail = observed ? useQuery : () => undefined
    const { result } = renderHook(
      () => ({ detail: useDetail(applicationQuery(row.id)), save: useSaveDraft(row.id) }),
      { wrapper },
    )
    if (!observed) await queryClient.fetchQuery(applicationQuery(row.id))
    await waitFor(() => expect(queryClient.getQueryData(queryKey)?.revision).toBe(1))
    expect(queryClient.getQueryCache().find({ queryKey })?.isActive()).toBe(observed)

    const polling = queryClient.refetchQueries({ queryKey })
    await pollStarted.promise
    await result.current.save.mutateAsync({ purpose_text: 'текст' })
    expect(queryClient.getQueryData(queryKey)).toMatchObject({
      revision: 2,
      purpose_text: 'ответ PATCH',
    })

    releasePoll.resolve()
    await pollAnswered.promise
    await polling
    expect(queryClient.getQueryData(queryKey)).toMatchObject({
      revision: 2,
      purpose_text: 'ответ PATCH',
    })
  })

  describe('правила storeApplication', () => {
    const base = { id: 'a1', purpose_text: 'кэш' } as const
    const view = (revision: unknown, purpose_text: string) =>
      ({ ...base, revision, purpose_text }) as unknown as Parameters<typeof storeApplication>[1]
    const run = (
      cached: unknown,
      incoming: ReturnType<typeof view>,
      mark: SessionMark | undefined,
    ) => {
      const queryClient = createQueryClient({ onUnauthorized: () => {} })
      if (cached !== undefined)
        queryClient.setQueryData(applicationQuery('a1').queryKey, cached as never)
      const stored = storeApplication(queryClient, incoming, mark)
      return { stored, data: queryClient.getQueryData(applicationQuery('a1').queryKey) }
    }

    it.each([
      ['ревизия больше — пишем', view(3, 'кэш'), view(4, 'ответ'), 'ответ'],
      ['ревизия равна — оставляем кэш', view(3, 'кэш'), view(3, 'ответ'), 'кэш'],
      ['ревизия меньше — оставляем кэш', view(3, 'кэш'), view(2, 'ответ'), 'кэш'],
      ['в кэше пусто — пишем', undefined, view(1, 'ответ'), 'ответ'],
      ['в кэше нет ревизии — пишем', view(undefined, 'кэш'), view(1, 'ответ'), 'ответ'],
      ['у ответа нет ревизии — оставляем кэш', view(3, 'кэш'), view(undefined, 'ответ'), 'кэш'],
    ])('%s', (_, cached, incoming, expected) => {
      expect(run(cached, incoming, markSession()).data).toMatchObject({ purpose_text: expected })
    })

    it('метка другой сессии или её нет — ничего не пишем', () => {
      const stale = markSession()
      auth.clear()
      expect(run(undefined, view(1, 'ответ'), stale)).toEqual({ stored: false, data: undefined })
      expect(run(undefined, view(1, 'ответ'), undefined)).toEqual({
        stored: false,
        data: undefined,
      })
    })
  })
})
