import { describe, expect, it, vi } from 'vitest'
import { ApiError, NETWORK_ERROR } from '@/api/errors.ts'
import { createQueryClient, shouldRetry } from './query-client.ts'

vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))
const { toast } = await import('sonner')

describe('shouldRetry', () => {
  it('повторяет только 5xx и не больше двух раз', () => {
    const server = new ApiError(503, 'PROVIDER_UNAVAILABLE', 'down')
    expect(shouldRetry(0, server)).toBe(true)
    expect(shouldRetry(1, server)).toBe(true)
    expect(shouldRetry(2, server)).toBe(false)
    expect(shouldRetry(0, new ApiError(422, 'VALIDATION_ERROR', 'bad'))).toBe(false)
    expect(shouldRetry(0, new ApiError(0, NETWORK_ERROR, 'offline'))).toBe(false)
  })
})

describe('глобальная обработка ошибок', () => {
  const run = (queryClient: ReturnType<typeof createQueryClient>, error: ApiError, meta = {}) =>
    queryClient
      .getMutationCache()
      .build(queryClient, {
        mutationFn: () => Promise.reject(error),
        meta,
      })
      .execute(undefined)
      .catch(() => undefined)

  it('401 сессии — выход', async () => {
    const onUnauthorized = vi.fn()
    await run(createQueryClient({ onUnauthorized }), new ApiError(401, 'UNAUTHORIZED', 'x'))
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('неверный пароль — не выход, а текст ошибки', async () => {
    const onUnauthorized = vi.fn()
    await run(createQueryClient({ onUnauthorized }), new ApiError(401, 'INVALID_CREDENTIALS', 'x'))
    expect(onUnauthorized).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenLastCalledWith('Неверный логин или пароль')
  })

  it('409 REVISION_CONFLICT — сообщение и обновление данных', async () => {
    const queryClient = createQueryClient({ onUnauthorized: vi.fn() })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    await run(queryClient, new ApiError(409, 'REVISION_CONFLICT', 'x'), {
      invalidates: [['applications', '42']],
      errorToast: false,
    })
    expect(toast.error).toHaveBeenLastCalledWith(expect.stringContaining('Заявка изменилась'))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['applications', '42'] })
  })

  it('после успеха инвалидирует ключи из meta', async () => {
    const queryClient = createQueryClient({ onUnauthorized: vi.fn() })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    await queryClient
      .getMutationCache()
      .build(queryClient, {
        mutationFn: () => Promise.resolve('ok'),
        meta: { invalidates: [['applications']] },
      })
      .execute(undefined)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['applications'] })
  })
})
