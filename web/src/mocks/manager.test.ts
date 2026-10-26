import { describe, expect, it } from 'vitest'
import { api, unwrap } from '@/api/client.ts'
import { demoUser, signInAs } from '@/test/session.ts'
import { db, seedManagerQueue } from './db.ts'
import { AI_REPORT_DELAY_MS, aiReportFor, offerPreview } from './manager-views.ts'
import { setScenario } from './scenarios.ts'

const failure = (request: Promise<unknown>) =>
  request.then(
    () => null,
    (error: unknown) => error,
  )

function applicationOf(login: string) {
  const owner = demoUser(login)
  const application = db.listApplications().find((item) => item.owner_user_id === owner.id)
  if (!application) throw new Error(`Нет заявки у ${login}`)
  return application
}

describe('демо-очередь менеджера', () => {
  it('семь заявок C1–C7 на рассмотрении, клиенты привязаны к компаниям', () => {
    seedManagerQueue()
    const queue = db.listApplications()
    expect(queue).toHaveLength(7)
    expect(queue.every((item) => item.status === 'UNDER_REVIEW')).toBe(true)
    expect(demoUser('director.bakery').company_id).not.toBeNull()
  })
})

describe('предпросмотр встречного предложения', () => {
  it('C2: лимит на 36 мес. — 2 340 000, на нём условия проходят', () => {
    seedManagerQueue()
    const application = applicationOf('director.bakery')
    const preview = offerPreview(application, 2_340_000, 36)
    expect(preview).toMatchObject({
      calculation_status: 'OK',
      limit_for_term_rub: '2340000.00',
      valid: true,
      violations: [],
    })
  })

  it('выше лимита и без улучшения — нарушения, расчёт всё равно виден', () => {
    seedManagerQueue()
    const application = applicationOf('director.bakery')
    expect(offerPreview(application, 2_900_000, 36).violations).toEqual(['AMOUNT_ABOVE_LIMIT'])
    expect(offerPreview(application, 3_000_000, 36)).toMatchObject({
      valid: false,
      violations: ['AMOUNT_ABOVE_LIMIT', 'OFFER_NOT_IMPROVED'],
    })
  })

  it('вне рассмотрения — 409', async () => {
    seedManagerQueue()
    await signInAs('manager.anna')
    const application = applicationOf('director.bakery')
    application.status = 'APPROVED'
    const error = await failure(
      unwrap(
        api.POST('/api/v1/manager/applications/{application_id}/offer-preview', {
          params: { path: { application_id: application.id } },
          body: { amount_rub: 2_000_000, term_months: 36 },
        }),
      ),
    )
    expect(error).toMatchObject({ status: 409, code: 'INVALID_STATUS_TRANSITION' })
  })
})

describe('решения менеджера', () => {
  const decide = (id: string, body: Record<string, unknown>) =>
    failure(
      unwrap(
        api.POST('/api/v1/manager/applications/{application_id}/decisions', {
          params: {
            path: { application_id: id },
            header: { 'Idempotency-Key': crypto.randomUUID() },
          },
          body: body as never,
        }),
      ),
    )

  it('отказ без комментария — 422 по полю', async () => {
    seedManagerQueue()
    await signInAs('manager.anna')
    const application = applicationOf('director.vector')
    const error = await decide(application.id, {
      action: 'REJECT',
      revision: application.revision,
      client_reason_code: 'COMPANY_STATUS',
    })
    expect(error).toMatchObject({ status: 422, code: 'VALIDATION_ERROR' })
    expect(application.status).toBe('UNDER_REVIEW')
  })

  it('оффер выше лимита — 422 AMOUNT_ABOVE_LIMIT', async () => {
    seedManagerQueue()
    await signInAs('manager.anna')
    const application = applicationOf('director.bakery')
    const error = await decide(application.id, {
      action: 'COUNTER_OFFER',
      revision: application.revision,
      amount_rub: 2_900_000,
      term_months: 36,
      client_reason_code: 'HIGH_DEBT_LOAD',
      comment: 'Предлагаем меньше',
    })
    expect(error).toMatchObject({ status: 422, code: 'AMOUNT_ABOVE_LIMIT' })
  })

  it('одобрение вопреки рекомендации требует комментарий', async () => {
    seedManagerQueue()
    await signInAs('manager.anna')
    const application = applicationOf('ip.orlov')
    const error = await decide(application.id, {
      action: 'APPROVE',
      revision: application.revision,
    })
    expect(error).toMatchObject({ status: 422, code: 'VALIDATION_ERROR' })
  })
})

describe('AI-заключение', () => {
  it('готовится AI_REPORT_DELAY_MS после отправки, потом READY', () => {
    seedManagerQueue()
    const application = applicationOf('director.techservice')
    const submitted = Date.parse(application.submitted_at ?? '')
    expect(aiReportFor(application, undefined, submitted + 1)?.status).toBe('PENDING')
    const ready = aiReportFor(application, undefined, submitted + AI_REPORT_DELAY_MS)
    expect(ready).toMatchObject({ status: 'READY', llm_mode: 'replay' })
    expect(ready?.report?.positive_factors.map((factor) => factor.code)).toContain(
      'DSCR_MEETS_TARGET',
    )
  })

  it('модель недоступна — шаблонный FALLBACK', () => {
    seedManagerQueue()
    setScenario('unavailable')
    const report = aiReportFor(applicationOf('director.techservice'))
    expect(report).toMatchObject({
      status: 'FALLBACK',
      fallback_reason: 'UNAVAILABLE',
      llm_mode: 'disabled',
      model_id: null,
    })
    expect(report?.report?.summary).toBeTruthy()
  })

  it('повторная оценка того же менеджера заменяет прошлую', async () => {
    seedManagerQueue()
    await signInAs('manager.anna')
    const application = applicationOf('director.techservice')
    const report = aiReportFor(application)
    if (!report) throw new Error('Нет заключения')
    const rate = (verdict: 'UP' | 'DOWN') =>
      unwrap(
        api.POST('/api/v1/manager/applications/{application_id}/ai-feedback', {
          params: { path: { application_id: application.id } },
          body: { ai_report_id: report.id, verdict },
        }),
      )
    await rate('UP')
    await rate('DOWN')
    expect(db.listFeedback().map((row) => row.verdict)).toEqual(['DOWN'])
    const stats = await unwrap(api.GET('/api/v1/manager/stats'))
    expect(stats.ai_feedback_groups).toEqual([
      expect.objectContaining({ total: 1, up_count: 0, up_share: '0.00' }),
    ])
  })
})
