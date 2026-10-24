import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { api, unwrap } from '@/api/client.ts'
import { ApiError, NETWORK_ERROR } from '@/api/errors.ts'
import { db } from '@/mocks/db.ts'
import { server } from '@/test/server.ts'
import { signInWithCompany } from '@/test/session.ts'
import { useIdempotentMutation } from './idempotency.ts'

type Fn = (variables: { text: string }, key: string) => Promise<string>

function setup(mutationFn: Fn) {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return renderHook(() => useIdempotentMutation({ mutationFn }), { wrapper })
}

const networkError = () => new ApiError(0, NETWORK_ERROR, 'offline')

describe('useIdempotentMutation', () => {
  it('новое действие после успеха — новый ключ', async () => {
    const fn = vi.fn<Fn>(async () => 'ok')
    const { result } = setup(fn)
    await act(() => result.current.mutateAsync({ text: 'a' }))
    await act(() => result.current.mutateAsync({ text: 'a' }))
    const [first, second] = fn.mock.calls.map((call) => call[1])
    expect(first).toMatch(/^[0-9a-f-]{36}$/)
    expect(second).not.toBe(first)
  })

  it('повтор после сетевой ошибки — с тем же ключом', async () => {
    const fn = vi.fn<Fn>().mockRejectedValueOnce(networkError()).mockResolvedValueOnce('ok')
    const { result } = setup(fn)
    await act(() => result.current.mutateAsync({ text: 'a' }).catch(() => undefined))
    await act(() => result.current.mutateAsync({ text: 'a' }))
    expect(fn.mock.calls[1]?.[1]).toBe(fn.mock.calls[0]?.[1])
  })

  it('повтор после 5xx — с тем же ключом', async () => {
    const fn = vi
      .fn<Fn>()
      .mockRejectedValueOnce(new ApiError(503, 'PROVIDER_UNAVAILABLE', 'down'))
      .mockResolvedValueOnce('ok')
    const { result } = setup(fn)
    await act(() => result.current.mutateAsync({ text: 'a' }).catch(() => undefined))
    await act(() => result.current.mutateAsync({ text: 'a' }))
    expect(fn.mock.calls[1]?.[1]).toBe(fn.mock.calls[0]?.[1])
  })

  it('после 4xx — новый ключ', async () => {
    const fn = vi
      .fn<Fn>()
      .mockRejectedValueOnce(new ApiError(409, 'REVISION_CONFLICT', 'conflict'))
      .mockResolvedValueOnce('ok')
    const { result } = setup(fn)
    await act(() => result.current.mutateAsync({ text: 'a' }).catch(() => undefined))
    await act(() => result.current.mutateAsync({ text: 'a' }))
    expect(fn.mock.calls[1]?.[1]).not.toBe(fn.mock.calls[0]?.[1])
  })

  it('изменились данные после сетевой ошибки — новый ключ', async () => {
    const fn = vi.fn<Fn>().mockRejectedValueOnce(networkError()).mockResolvedValueOnce('ok')
    const { result } = setup(fn)
    await act(() => result.current.mutateAsync({ text: 'a' }).catch(() => undefined))
    await act(() => result.current.mutateAsync({ text: 'b' }))
    expect(fn.mock.calls[1]?.[1]).not.toBe(fn.mock.calls[0]?.[1])
  })

  it('isPending на время запроса — по нему блокируется кнопка', async () => {
    let finish: (value: string) => void = () => {}
    const fn = vi.fn<Fn>(() => new Promise<string>((resolve) => (finish = resolve)))
    const { result } = setup(fn)
    act(() => result.current.mutate({ text: 'a' }))
    await waitFor(() => expect(result.current.isPending).toBe(true))
    act(() => finish('ok'))
    await waitFor(() => expect(result.current.isPending).toBe(false))
  })
})

function deferred() {
  let resolve: () => void = () => {}
  const promise = new Promise<void>((done) => (resolve = done))
  return { promise, resolve }
}

describe('useIdempotentMutation и IDEMPOTENCY_IN_PROGRESS моков', () => {
  it('пока первая отправка выполняется, повторы идут с тем же ключом и не дублируют её', async () => {
    const user = await signInWithCompany('director.bakery', '0099020010')
    const draft = await unwrap(api.POST('/api/v1/applications', { body: {} }))
    const filled = await unwrap(
      api.PATCH('/api/v1/applications/{application_id}', {
        params: { path: { application_id: draft.id } },
        body: {
          revision: draft.revision,
          purpose_code: 'EQUIPMENT',
          requested_amount_rub: 3_000_000,
          term_months: 36,
          product_id: 'investment',
          terms_field_sources: {
            purpose_code: 'MANUAL',
            requested_amount_rub: 'MANUAL',
            term_months: 'MANUAL',
          },
        },
      }),
    )

    // Фактические заголовки запросов и барьеры: N-й запрос ждёт release[N] до обработчика.
    const sent: (string | null)[] = []
    const arrived = [deferred(), deferred(), deferred(), deferred()]
    const release = [deferred(), deferred(), deferred(), deferred()]
    const held = new Set([0, 2])
    server.use(
      http.post(`/api/v1/applications/:application_id/submit`, async ({ request }) => {
        const n = sent.push(request.headers.get('Idempotency-Key')) - 1
        arrived[n]?.resolve()
        if (!held.has(n)) return undefined
        if (n === 0) {
          // Первая отправка «в работе» на сервере: ключ занят, как в долгом обработчике.
          const row = db.idempotency(user.id, request.headers.get('Idempotency-Key') ?? '')
          const body = await request.clone().text()
          row.set({
            fingerprint: `POST ${new URL(request.url).pathname} ${body}`,
            state: 'in_progress',
          })
          await release[n]?.promise
          row.release()
        } else {
          await release[n]?.promise
        }
        // Дальше — настоящий обработчик моков.
        return undefined
      }),
    )

    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(
      () =>
        useIdempotentMutation({
          mutationFn: (revision: number, key: string) =>
            unwrap(
              api.POST('/api/v1/applications/{application_id}/submit', {
                params: { path: { application_id: filled.id }, header: { 'Idempotency-Key': key } },
                body: { revision, bki_consent_version: 'bki-v1' },
              }),
            ),
        }),
      { wrapper },
    )
    const attempt = (revision: number) =>
      result.current.mutateAsync(revision).catch((e: unknown) => e)

    const first = attempt(filled.revision)
    await arrived[0]?.promise
    // Параллельный повтор того же действия — 409, ключ остаётся.
    expect(await attempt(filled.revision)).toMatchObject({
      status: 409,
      code: 'IDEMPOTENCY_IN_PROGRESS',
    })
    // Следующая попытка с тем же телом уходит с K1 и доходит до сервера после первой.
    const retry = attempt(filled.revision)
    await arrived[2]?.promise
    release[0]?.resolve()
    const submitted = await first
    expect(submitted).toMatchObject({ status: 'UNDER_REVIEW', revision: filled.revision + 1 })
    release[2]?.resolve()
    // Сохранённый ответ первой отправки, а не новая обработка.
    expect(await retry).toEqual(submitted)
    expect(db.findApplication(filled.id)).toMatchObject({ revision: filled.revision + 1 })

    // Другое тело — новое действие и новый ключ.
    await attempt(filled.revision + 1)
    const [k1, ...rest] = sent
    expect(k1).toMatch(/^[0-9a-f-]{36}$/)
    expect(rest.slice(0, 2)).toEqual([k1, k1])
    expect(rest[2]).not.toBe(k1)
    expect(sent).toHaveLength(4)
  })
})
