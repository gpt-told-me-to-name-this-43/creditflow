import { describe, expect, it } from 'vitest'
import { APPLICATION_STATUSES } from '@/api/enums.ts'
import { applicationRefetchInterval, isFinal } from './polling.ts'

describe('isFinal', () => {
  it('финальны только отказ, отказ клиента и выдача', () => {
    const final = APPLICATION_STATUSES.filter((status) => isFinal(status))
    expect(final).toEqual(['REJECTED', 'DECLINED', 'ISSUED'])
  })

  it('пока данных нет — не финал', () => {
    expect(isFinal(undefined)).toBe(false)
  })
})

describe('applicationRefetchInterval', () => {
  it('опрашивает раз в 5 с, после подписания — раз в 2 с, в финале — нет', () => {
    expect(applicationRefetchInterval('UNDER_REVIEW')).toBe(5000)
    expect(applicationRefetchInterval(undefined)).toBe(5000)
    expect(applicationRefetchInterval('SIGNED')).toBe(2000)
    expect(applicationRefetchInterval('ISSUED')).toBe(false)
  })
})
