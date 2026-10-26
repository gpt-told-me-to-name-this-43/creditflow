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

// Кабинет менеджера (#10).
export type SuggestedAction = Schemas['SuggestedAction']
export type StopFactor = Schemas['StopFactor']
export type ReasonCode = Schemas['ReasonCode']
export type RiskLevel = Schemas['RiskLevel']
export type ManagerAction = Schemas['ManagerAction']
export type RuleId = Schemas['RuleTraceItem']['rule']
export type Provider = Schemas['ExternalSource']['provider']
export type FallbackReason = Schemas['FallbackReason']

export const SUGGESTED_ACTIONS = allOf<SuggestedAction>()(
  'BLOCKED_BY_RULE',
  'MANUAL_REVIEW',
  'COUNTER_OFFER_CANDIDATE',
  'ELIGIBLE_FOR_MANAGER_REVIEW',
)

export const STOP_FACTORS = allOf<StopFactor>()(
  'COMPANY_INACTIVE',
  'APPLICANT_NOT_AUTHORIZED',
  'BANKRUPTCY_PROCEEDING',
  'ACCOUNT_BLOCKED_BY_FNS',
  'ACCOUNT_HISTORY_INSUFFICIENT',
)

export const REASON_CODES = allOf<ReasonCode>()(
  'DSCR_BELOW_ONE',
  'DSCR_BELOW_TARGET',
  'CREDIT_HISTORY_SERIOUS',
  'CREDIT_HISTORY_MINOR',
  'CREDIT_HISTORY_UNKNOWN',
  'REVENUE_DECLINE',
  'REVENUE_SHARP_DECLINE',
  'YOUNG_BUSINESS',
  'DSCR_MEETS_TARGET',
  'CLEAN_CREDIT_HISTORY',
  'REVENUE_STABLE_OR_GROWING',
  'ESTABLISHED_BUSINESS',
)

export const RISK_LEVELS = allOf<RiskLevel>()('LOW', 'MODERATE', 'HIGH', 'VERY_HIGH')

export const MANAGER_ACTIONS = allOf<ManagerAction>()(
  'APPROVE',
  'COUNTER_OFFER',
  'REQUEST_INFO',
  'REJECT',
)

export const RULE_IDS = allOf<RuleId>()('R1', 'R2', 'R3', 'R4', 'R5')

export const PROVIDERS = allOf<Provider>()('EGRUL', 'EGRIP', 'FNS', 'BKI', 'BANK')
