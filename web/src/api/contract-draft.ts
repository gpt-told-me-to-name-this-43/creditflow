/*
 * ВРЕМЕННО, до contract-v1 (#6). В docs/openapi.json пока только /health, поэтому
 * перечисления скопированы из api/app/schemas (ветка feat/6_findemo_and_test_data).
 * Когда контракт появится: `pnpm gen:api`, типы ниже заменить на components['schemas'][…]
 * из schema.d.ts, файл удалить. Других самописных типов API в проекте нет.
 */

export const APPLICATION_STATUSES = [
  'DRAFT',
  'UNDER_REVIEW',
  'APPROVED',
  'REJECTED',
  'COUNTER_OFFER',
  'NEED_INFO',
  'DECLINED',
  'SIGNED',
  'ISSUED',
] as const
export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number]

export const PURPOSE_CODES = [
  'EQUIPMENT',
  'RENOVATION',
  'BUSINESS_EXPANSION',
  'INVENTORY',
  'SUPPLIERS',
  'WORKING_CAPITAL',
] as const
export type PurposeCode = (typeof PURPOSE_CODES)[number]

export const CLIENT_REASON_CODES = [
  'COMPANY_STATUS',
  'APPLICANT_NOT_AUTHORIZED',
  'TAX_AUTHORITY_RESTRICTIONS',
  'INSUFFICIENT_DATA',
  'HIGH_DEBT_LOAD',
  'LOW_SCORE',
] as const
export type ClientReasonCode = (typeof CLIENT_REASON_CODES)[number]

// Источник истины — ErrorCode в api/app/schemas/common.py и таблица docs/api.md.
export const ERROR_CODES = [
  'UNAUTHORIZED',
  'INVALID_CREDENTIALS',
  'FORBIDDEN',
  'APPLICANT_NOT_AUTHORIZED',
  'NOT_FOUND',
  'REVISION_CONFLICT',
  'INVALID_STATUS_TRANSITION',
  'IDEMPOTENCY_IN_PROGRESS',
  'COMPANY_ALREADY_BOUND',
  'USER_ALREADY_BOUND',
  'VALIDATION_ERROR',
  'INVALID_INN',
  'COMPANY_NOT_IN_REGISTRY',
  'CONSENT_REQUIRED',
  'ACTION_NOT_ALLOWED',
  'AMOUNT_ABOVE_LIMIT',
  'SIGN_CODE_INVALID',
  'IDEMPOTENCY_KEY_REUSED',
  'TOO_MANY_ATTEMPTS',
  'PROVIDER_UNAVAILABLE',
] as const
export type ErrorCode = (typeof ERROR_CODES)[number]
