import { type QueryClient, queryOptions, replaceEqualDeep } from '@tanstack/react-query'
import { isCurrentSession, type SessionMark } from '@/lib/auth.ts'
import { applicationRefetchInterval, isFinal, POLL_INTERVAL_MS } from '@/lib/polling.ts'
import { api, unwrap } from '../client.ts'
import type { components } from '../schema.d.ts'
import { queryKeys } from './keys.ts'

type Application = components['schemas']['ClientApplicationView']

export { markSession, type SessionMark } from '@/lib/auth.ts'

const revisionOf = (value: unknown) => (value as { revision?: unknown } | undefined)?.revision

/**
 * Запись ответа GET (structuralSharing выполняется синхронно внутри записи в кэш):
 * запоздавший ответ с меньшей ревизией не откатывает кэш. Равная ревизия — данные GET
 * (та же версия, прочитана позже); нет числовых ревизий — тоже данные GET.
 */
function keepNewerSnapshot(previous: unknown, incoming: unknown) {
  const was = revisionOf(previous)
  const next = revisionOf(incoming)
  if (typeof was === 'number' && typeof next === 'number' && next < was) return previous
  return replaceEqualDeep(previous, incoming)
}

/**
 * Единственный способ положить в кэш карточку из ответа мутации.
 *
 * MutationCache.onSuccess ждёт invalidate → refetch и только потом зовёт локальный onSuccess,
 * поэтому ответ мутации может оказаться старше снимка в кэше. Ревизия на бэке растёт при каждой
 * записи (design.md §3.7, `revision += 1`), поэтому порядок снимков задаёт она, а не время:
 * - ревизия ответа больше закэшированной — пишем;
 * - равна или меньше — оставляем кэш (та же или более поздняя версия, refetch не старше ответа);
 * - в кэше нет карточки или у неё нет числовой ревизии — пишем ответ;
 * - у ответа нет числовой ревизии при числовой в кэше — оставляем кэш.
 * Сессия сменилась после старта мутации (или метки нет) — не пишем ничего: `false`,
 * и вызывающий не продолжает (навигация и прочее).
 */
export function storeApplication(
  queryClient: QueryClient,
  application: Application,
  mark: SessionMark | undefined,
): boolean {
  if (!isCurrentSession(mark)) return false
  queryClient.setQueryData(applicationQuery(application.id).queryKey, (previous) =>
    typeof previous?.revision === 'number' && !(application.revision > previous.revision)
      ? previous
      : application,
  )
  return true
}

export const applicationsQuery = () =>
  queryOptions({
    queryKey: queryKeys.applications.all,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/applications', { signal })),
    // Список обновляется, пока хоть одна отправленная заявка ждёт решения или выдачи.
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status !== 'DRAFT' && !isFinal(item.status))
        ? POLL_INTERVAL_MS
        : false,
  })

export const applicationQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.applications.detail(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/applications/{application_id}', {
          params: { path: { application_id: id } },
          signal,
        }),
      ),
    structuralSharing: keepNewerSnapshot,
    // Черновик меняет только сам клиент — опрашивать нечего; дальше решение приходит с бэка.
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'DRAFT' ? false : applicationRefetchInterval(status)
    },
  })

export const contractQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.applications.contract(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/applications/{application_id}/contract', {
          params: { path: { application_id: id } },
          signal,
        }),
      ),
  })
