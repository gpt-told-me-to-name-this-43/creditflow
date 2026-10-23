import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, NETWORK_ERROR } from '@/api/errors.ts'
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
