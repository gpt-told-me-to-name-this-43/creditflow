import type { ApplicationStatus } from '@/api/enums.ts'

// Тексты страницы заявки (/client/applications/$applicationId).

export const applicationTexts = {
  backToList: 'Мои заявки',
  title: 'Заявка',
  requestTitle: 'Что вы просили',
  submittedAt: (date: string) => `Отправлена ${date}`,
  newApplication: 'Подать новую заявку',
  statusChanged: (label: string) => `Статус заявки: ${label}`,
} as const

export const reviewBlockTexts = {
  title: 'Что мы проверяем',
  checks: [
    'Сведения о компании в государственном реестре',
    'Нет ли ограничений налоговой службы по счёту',
    'Кредитную историю компании',
    'Обороты по счёту за последний год',
  ],
  yourAnswer: 'Ваш ответ менеджеру',
} as const

export const infoRequestTexts = {
  title: 'Вопрос менеджера',
  answerLabel: 'Ваш ответ',
  answerHint: 'Ответьте как можно подробнее — менеджер продолжит рассмотрение сразу после ответа',
  answerRequired: 'Напишите ответ',
  send: 'Отправить ответ',
  sending: 'Отправляем…',
} as const

export const offerTexts = {
  title: 'Банк предлагает другие условия',
  description: 'Сравните с тем, что вы просили. Можно принять предложение или отказаться',
  condition: 'Условие',
  requested: 'Вы просили',
  offered: 'Банк предлагает',
  rows: {
    amount: 'Сумма',
    term: 'Срок',
    rate: 'Ставка',
    payment: 'Платёж в месяц',
    overpayment: 'Переплата за весь срок',
  },
  months: (n: number) => `${n} мес.`,
  changed: 'Изменено',
  paymentLess: (sum: string) => `Платёж меньше на ${sum}`,
  paymentMore: (sum: string) => `Платёж больше на ${sum}`,
  overpaymentMore: (sum: string) => `переплата больше на ${sum}`,
  overpaymentLess: (sum: string) => `переплата меньше на ${sum}`,
  accept: 'Принять предложение',
  decline: 'Отказаться',
  acceptTitle: 'Принять предложение банка?',
  acceptDescription: 'Подготовим договор на новых условиях. Подписать его можно будет сразу',
  declineTitle: 'Отказаться от предложения?',
  declineDescription:
    'Заявка будет закрыта. Если передумаете, можно будет подать новую заявку с другими условиями',
  confirmAccept: 'Да, принять',
  confirmDecline: 'Да, отказаться',
  cancel: 'Отмена',
} as const

export const rejectedTexts = {
  title: 'Почему банк отказал',
  whatToDo: 'Что можно сделать',
} as const

export const declinedTexts = {
  title: 'Вы отказались от предложения банка',
  description: 'Заявка закрыта. Можно подать новую — например, с другой суммой или сроком',
} as const

export const approvedTexts = {
  title: 'Кредит одобрен',
  description: 'Проверьте условия договора ниже и подпишите его кодом подтверждения',
} as const

export const disbursementTexts = {
  signedTitle: 'Зачисляем средства…',
  signedDescription: 'Договор подписан. Деньги придут на ваш счёт через несколько секунд',
  issuedTitle: 'Средства зачислены',
  amount: 'Сумма',
  account: 'Счёт зачисления',
  firstPayment: 'Первый платёж',
  monthlyPayment: 'Платёж в месяц',
} as const

/** Подпись события таймлайна по переходу статусов. */
export function timelineText(from: ApplicationStatus | null, to: ApplicationStatus): string {
  if (from === null) return 'Заявка создана'
  if (from === 'NEED_INFO' && to === 'UNDER_REVIEW') return 'Вы ответили на вопрос менеджера'
  if (from === 'COUNTER_OFFER' && to === 'APPROVED') return 'Вы приняли предложение банка'
  return timelineByStatus[to]
}

const timelineByStatus = {
  DRAFT: 'Заявка создана',
  UNDER_REVIEW: 'Заявка отправлена на рассмотрение',
  NEED_INFO: 'Менеджер задал вопрос',
  COUNTER_OFFER: 'Банк предложил другие условия',
  APPROVED: 'Кредит одобрен',
  REJECTED: 'Банк отказал',
  DECLINED: 'Вы отказались от предложения',
  SIGNED: 'Договор подписан',
  ISSUED: 'Деньги зачислены на счёт',
} as const satisfies Record<ApplicationStatus, string>

export const timelineTitle = 'История заявки'
