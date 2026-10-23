import type { ClientReasonCode } from '@/api/contract-draft.ts'

interface ReasonText {
  /** Почему банк отказал — без внутренних метрик и кодов. */
  reason: string
  /** Что клиент может сделать. */
  whatToDo: string
}

export const reasonTexts = {
  COMPANY_STATUS: {
    reason: 'По данным реестра компания не числится действующей',
    whatToDo: 'Если данные в реестре устарели, подайте заявку снова после их обновления',
  },
  APPLICANT_NOT_AUTHORIZED: {
    reason: 'Подать заявку может только руководитель компании или сам ИП',
    whatToDo: 'Попросите руководителя войти в кабинет и подать заявку',
  },
  TAX_AUTHORITY_RESTRICTIONS: {
    reason: 'По счёту компании есть ограничения налоговой службы',
    whatToDo: 'Подайте заявку снова, когда ограничения будут сняты',
  },
  INSUFFICIENT_DATA: {
    reason: 'По счёту пока мало операций, чтобы оценить бизнес',
    whatToDo: 'Подайте заявку, когда по счёту накопится хотя бы полгода операций',
  },
  HIGH_DEBT_LOAD: {
    reason: 'Платежи по текущим кредитам уже большие по сравнению с доходами',
    whatToDo: 'Попробуйте меньшую сумму или более долгий срок',
  },
  LOW_SCORE: {
    reason: 'Финансовые показатели бизнеса пока не позволяют выдать кредит',
    whatToDo: 'Подайте заявку позже, когда обороты по счёту вырастут',
  },
} as const satisfies Record<ClientReasonCode, ReasonText>
