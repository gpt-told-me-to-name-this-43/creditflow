import type { components } from './schema.d.ts'

/*
 * Перечисления контракта в рантайме: типы — из schema.d.ts, а массивы нужны тестам полноты
 * content/ и мокам. Если в контракте появится значение, которого нет в списке, — ошибка
 * компиляции: `pnpm gen:api` сразу покажет, где не хватает текста.
 */

type Schemas = components['schemas']

export type ApplicationStatus = Schemas['ApplicationStatus']
export type PurposeCode = Schemas['PurposeCode']
export type ClientReasonCode = Schemas['ClientReasonCode']
export type ErrorCode = Schemas['ErrorCode']
export type Role = Schemas['Role']

/** Принимает только полный список значений `T`, без лишних и пропусков. */
function allOf<T extends string>() {
  return <const V extends readonly T[]>(
    ...values: V & ([T] extends [V[number]] ? unknown : 'не хватает значений')
  ): V => values
}

export const ROLES = allOf<Role>()('CLIENT', 'MANAGER')

export const APPLICATION_STATUSES = allOf<ApplicationStatus>()(
  'DRAFT',
  'UNDER_REVIEW',
  'APPROVED',
  'REJECTED',
  'COUNTER_OFFER',
  'NEED_INFO',
  'DECLINED',
  'SIGNED',
  'ISSUED',
)

export const PURPOSE_CODES = allOf<PurposeCode>()(
  'EQUIPMENT',
  'RENOVATION',
  'BUSINESS_EXPANSION',
  'INVENTORY',
  'SUPPLIERS',
  'WORKING_CAPITAL',
)

export const CLIENT_REASON_CODES = allOf<ClientReasonCode>()(
  'COMPANY_STATUS',
  'APPLICANT_NOT_AUTHORIZED',
  'TAX_AUTHORITY_RESTRICTIONS',
  'INSUFFICIENT_DATA',
  'HIGH_DEBT_LOAD',
  'LOW_SCORE',
)

export const ERROR_CODES = allOf<ErrorCode>()(
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
  'COMPANY_NOT_BOUND',
  'VALIDATION_ERROR',
  'INVALID_INN',
  'COMPANY_NOT_IN_REGISTRY',
  'CONSENT_REQUIRED',
  'APPLICATION_INCOMPLETE',
  'PRODUCT_NOT_ELIGIBLE',
  'SIGN_CHALLENGE_EXPIRED',
  'ACTION_NOT_ALLOWED',
  'AMOUNT_ABOVE_LIMIT',
  'SIGN_CODE_INVALID',
  'IDEMPOTENCY_KEY_REUSED',
  'TOO_MANY_ATTEMPTS',
  'PROVIDER_UNAVAILABLE',
  'BAD_REQUEST',
  'METHOD_NOT_ALLOWED',
  'SERVICE_UNAVAILABLE',
  'INTERNAL_ERROR',
)
