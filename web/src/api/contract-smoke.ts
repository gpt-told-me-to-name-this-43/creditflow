/** Compile-time regression checks against the generated contract. */
import type { components, paths } from './schema'

type DTO = components['schemas']
type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false
type Assert<T extends true> = T
type JsonBody<T> = T extends { content: { 'application/json': infer V } } ? V : never
type Create = paths['/api/v1/applications']['post']['responses']
type AI = paths['/api/v1/manager/applications/{application_id}/ai-report']['post']['responses']
type Internal =
  'score' | 'scoring' | 'dscr' | 'limit_rub' | 'blocking_codes' | 'ai_report' | 'comment'

export type ContractSmoke = [
  Assert<Equal<JsonBody<Create[200]>, DTO['ClientApplicationView']>>,
  Assert<Equal<JsonBody<Create[201]>, DTO['ClientApplicationView']>>,
  Assert<Equal<JsonBody<AI[200]>, DTO['AiReportView']>>,
  Assert<Equal<JsonBody<AI[202]>, DTO['AiReportView']>>,
  Assert<Equal<Extract<keyof DTO['ClientApplicationView'], Internal>, never>>,
  Assert<Equal<DTO['ManagerApplicationView']['offer_constraints'], DTO['OfferConstraints'] | null>>,
  Assert<
    Equal<DTO['ProductNotEligibleDetails']['unmet_constraints'][number], DTO['ProductConstraint']>
  >,
  Assert<Equal<Extract<NonNullable<DTO['ErrorBody']['details']>, unknown[]>, never>>,
  Assert<Equal<DTO['ValidationDetails']['fields'][number]['field'], string>>,
  Assert<Equal<DTO['RevisionConflictDetails']['current_revision'], number>>,
]

export function missingFields(error: DTO['ErrorEnvelope']): string[] {
  const details = error.error.details
  return error.error.code === 'APPLICATION_INCOMPLETE' && details && 'missing_fields' in details
    ? details.missing_fields
    : []
}
