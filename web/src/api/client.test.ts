import { readFileSync } from 'node:fs'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { createApiClient } from './client'
import { missingFields } from './contract-smoke'
import type { components } from './schema'

type DTO = components['schemas']
const origin = 'http://creditflow.test'
const id = '7f3e2a10-0000-4000-8000-000000000001'
const draft: DTO['ClientApplicationView'] = {
  id,
  revision: 1,
  status: 'DRAFT',
  purpose_text: null,
  purpose_code: null,
  requested_amount_rub: null,
  term_months: null,
  product_id: null,
  terms_source: 'MANUAL',
  terms_field_sources: {},
  allowed_actions: ['EDIT', 'INTERPRET'],
  annual_rate_pct: null,
  monthly_payment_rub: null,
  overpayment_rub: null,
  submitted_at: null,
  client_reason_code: null,
  offer: null,
  info_request: null,
  timeline: [],
}
const report: DTO['AiReportView'] = {
  id,
  scoring_result_id: id,
  status: 'PENDING',
  llm_mode: 'replay',
  model_id: null,
  prompt_version: 'explain-v1',
  report: null,
  fallback_reason: null,
  updated_at: '2026-10-23T12:00:00Z',
}
const server = setupServer()
let api: ReturnType<typeof createApiClient>
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
  api = createApiClient(origin, () => 'msw-token')
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('typed API + MSW 2 contract smoke', () => {
  it.each([200, 201] as const)('POST applications %s', async (status) => {
    server.use(
      http.post(`${origin}/api/v1/applications`, ({ request }) => {
        expect(request.headers.get('Authorization')).toBe('Bearer msw-token')
        return HttpResponse.json(draft, { status })
      }),
    )
    const result = await api.POST('/api/v1/applications', { body: {} })
    expect(result.response.status).toBe(status)
    expect(result.data?.allowed_actions).toEqual(['EDIT', 'INTERPRET'])
  })

  it.each([200, 202] as const)('POST AI report %s', async (status) => {
    server.use(
      http.post(`${origin}/api/v1/manager/applications/:id/ai-report`, () =>
        HttpResponse.json(report, { status }),
      ),
    )
    const result = await api.POST('/api/v1/manager/applications/{application_id}/ai-report', {
      params: { path: { application_id: id } },
    })
    expect(result.response.status).toBe(status)
    expect(result.data?.status).toBe('PENDING')
  })

  it('returns named error details and preserves Idempotency-Key', async () => {
    const error: DTO['ErrorEnvelope'] = {
      error: {
        code: 'APPLICATION_INCOMPLETE',
        message: 'Заполните поля',
        details: {
          missing_fields: ['product_id'],
        },
      },
    }
    server.use(
      http.post(`${origin}/api/v1/applications/:id/submit`, ({ request }) => {
        expect(request.headers.get('Idempotency-Key')).toBe('smoke-action-key')
        return HttpResponse.json(error, { status: 422 })
      }),
    )
    const result = await api.POST('/api/v1/applications/{application_id}/submit', {
      params: { path: { application_id: id }, header: { 'Idempotency-Key': 'smoke-action-key' } },
      body: { revision: 1, bki_consent_version: 'bki-v1' },
    })
    expect(result.error && missingFields(result.error)).toEqual(['product_id'])
  })

  it('exposes main C2, nullable offer constraints and canonical product enums', () => {
    // These examples are validated by backend tests against their actual DTOs.
    const spec = JSON.parse(
      readFileSync(new URL('../../../docs/openapi.json', import.meta.url), 'utf8'),
    )
    const cards =
      spec.paths['/api/v1/manager/applications/{application_id}'].get.responses['200'].content[
        'application/json'
      ].examples
    expect(cards.under_review.value.offer_constraints.max_amount_rub).toBe('5000000.00')
    expect(cards.issued.value.offer_constraints).toBeNull()
    expect(cards.issued.value.requested_amount_rub).toBe('3000000.00')
    expect(cards.issued.value.offers[0].amount_rub).toBe('2340000.00')
    expect(cards.issued.value.contract.term_months).toBe(36)
    const constraints: DTO['ProductConstraint'][] = [
      'PURPOSE_NOT_ALLOWED',
      'TERM_ABOVE_PRODUCT_MAX',
    ]
    expect(constraints).toEqual(
      spec.paths['/api/v1/credit-products'].get.responses['200'].content['application/json']
        .example[1].unmet_constraints,
    )
  })
})
