import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import type { ApplicationStatus } from '@/api/enums.ts'
import { queryKeys } from '@/api/queries/keys.ts'
import { toast } from 'sonner'
import { applicationTexts } from '@/content/application.ts'
import { statusTexts } from '@/content/statuses.ts'

/**
 * Статус сменился по опросу (решение менеджера, выдача): тост и свежий договор —
 * его статус и даты подписания и выдачи меняются вместе с заявкой.
 */
export function useStatusChange(applicationId: string, status: ApplicationStatus) {
  const queryClient = useQueryClient()
  const previous = useRef(status)
  useEffect(() => {
    if (previous.current === status) return
    previous.current = status
    toast.info(applicationTexts.statusChanged(statusTexts[status].label), {
      description: statusTexts[status].now,
    })
    void queryClient.invalidateQueries({ queryKey: queryKeys.applications.contract(applicationId) })
  }, [applicationId, queryClient, status])
}
