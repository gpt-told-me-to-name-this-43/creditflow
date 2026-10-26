import type {
  ApplicationStatus,
  FallbackReason,
  ManagerAction,
  Provider,
  ReasonCode,
  RiskLevel,
  RuleId,
  StopFactor,
  SuggestedAction,
} from '@/api/enums.ts'
import type { components } from '@/api/schema.d.ts'

// Тексты кабинета менеджера. Здесь можно DSCR, score и лимит — это внутренний экран банка;
// на клиентские экраны эти тексты не попадают.

type Schemas = components['schemas']

/** Вкладки очереди — по статусу заявки, в порядке работы менеджера. */
export const queueTabs = [
  { status: 'UNDER_REVIEW', label: 'На рассмотрении' },
  { status: 'NEED_INFO', label: 'Ждут ответа' },
  { status: 'COUNTER_OFFER', label: 'Предложение отправлено' },
  { status: 'APPROVED', label: 'Одобрены' },
  { status: 'SIGNED', label: 'Подписаны' },
  { status: 'ISSUED', label: 'Выданы' },
  { status: 'REJECTED', label: 'Отказы' },
  { status: 'DECLINED', label: 'Клиент отказался' },
] as const satisfies readonly { status: ApplicationStatus; label: string }[]

export type QueueStatus = (typeof queueTabs)[number]['status']

export const queueTexts = {
  title: 'Заявки',
  tabsLabel: 'Статус заявок',
  tableLabel: 'Очередь заявок',
  company: 'Компания',
  request: 'Запрос',
  status: 'Статус',
  suggestion: 'Рекомендация',
  stopFactors: 'Стоп-факторы',
  submitted: 'Отправлена',
  waiting: (duration: string) => `ждёт ${duration}`,
  inn: (inn: string) => `ИНН ${inn}`,
  noSuggestion: 'Нет расчёта',
  noStopFactors: 'Нет',
  empty: {
    UNDER_REVIEW: 'Новых заявок нет — все рассмотрены',
    NEED_INFO: 'Никто из клиентов не ждёт ответа на вопрос',
    COUNTER_OFFER: 'Нет открытых встречных предложений',
    APPROVED: 'Нет одобренных заявок, ожидающих подписания',
    SIGNED: 'Нет заявок в выдаче',
    ISSUED: 'Выданных кредитов пока нет',
    REJECTED: 'Отказов пока нет',
    DECLINED: 'Клиенты не отказывались от предложений',
  } satisfies Record<QueueStatus, string>,
} as const

export const statsTexts = {
  title: 'Сводка',
  underReview: 'На рассмотрении',
  waitingClient: 'Ждут ответа клиента',
  waitingClientHint: 'Вопрос менеджера или встречное предложение',
  medianTime: 'Медианное время до решения',
  matching: 'Решения совпадают с рекомендацией',
  noData: 'Нет данных',
  distribution: 'Рекомендации системы',
  distributionEmpty: 'Рекомендаций пока нет',
  feedback: 'Оценки AI-заключений',
  feedbackModel: 'Модель',
  feedbackTemplate: 'Шаблон',
  notEnoughFeedback: 'Недостаточно оценок',
  feedbackShare: (share: string, total: number) => `${share} 👍 из ${total} оценок`,
} as const

export const suggestedActionTexts = {
  ELIGIBLE_FOR_MANAGER_REVIEW: {
    label: 'Можно одобрять',
    description: 'DSCR не ниже 1.25 и score от 80 — условия заявки проходят',
  },
  COUNTER_OFFER_CANDIDATE: {
    label: 'Встречное предложение',
    description: 'На запрошенных условиях DSCR ниже 1.25, но есть лимит на другие условия',
  },
  MANUAL_REVIEW: {
    label: 'Ручное рассмотрение',
    description: 'Автоматическая рекомендация невозможна — решение за менеджером',
  },
  BLOCKED_BY_RULE: {
    label: 'Стоп-фактор',
    description: 'Есть стоп-фактор: заявку можно только отклонить',
  },
} as const satisfies Record<SuggestedAction, { label: string; description: string }>

export const stopFactorTexts = {
  COMPANY_INACTIVE: 'Компания в ликвидации или ликвидирована (ЕГРЮЛ/ЕГРИП)',
  APPLICANT_NOT_AUTHORIZED: 'Заявитель не руководитель компании',
  BANKRUPTCY_PROCEEDING: 'Процедура банкротства (ФНС)',
  ACCOUNT_BLOCKED_BY_FNS: 'Действующие блокировки счетов (ФНС)',
  ACCOUNT_HISTORY_INSUFFICIENT: 'Меньше 6 месяцев истории по счёту',
} as const satisfies Record<StopFactor, string>

export const reasonCodeTexts = {
  DSCR_BELOW_ONE: 'DSCR ниже 1: доходов не хватает на платежи',
  DSCR_BELOW_TARGET: 'DSCR ниже целевого 1.25',
  CREDIT_HISTORY_SERIOUS: 'Серьёзные просрочки в кредитной истории',
  CREDIT_HISTORY_MINOR: 'Небольшие просрочки в кредитной истории',
  CREDIT_HISTORY_UNKNOWN: 'Кредитной истории нет',
  REVENUE_DECLINE: 'Выручка снизилась до 15%',
  REVENUE_SHARP_DECLINE: 'Выручка снизилась больше чем на 15%',
  YOUNG_BUSINESS: 'Бизнесу меньше 2 лет',
  DSCR_MEETS_TARGET: 'DSCR не ниже целевого 1.25',
  CLEAN_CREDIT_HISTORY: 'Кредитная история без просрочек',
  REVENUE_STABLE_OR_GROWING: 'Выручка стабильна или растёт',
  ESTABLISHED_BUSINESS: 'Бизнесу больше 2 лет',
} as const satisfies Record<ReasonCode, string>

export const riskLevelTexts = {
  LOW: 'Низкий',
  MODERATE: 'Умеренный',
  HIGH: 'Высокий',
  VERY_HIGH: 'Очень высокий',
} as const satisfies Record<RiskLevel, string>

export const managerActionTexts = {
  APPROVE: 'Одобрение',
  COUNTER_OFFER: 'Встречное предложение',
  REQUEST_INFO: 'Запрос информации',
  REJECT: 'Отказ',
} as const satisfies Record<ManagerAction, string>

/** Правила DecisionPolicy (design.md §3.4): первое сработавшее задаёт рекомендацию. */
export const ruleTexts = {
  R1: 'Есть стоп-фактор → стоп-фактор',
  R2: 'Кредитная история SERIOUS → ручное рассмотрение',
  R3: 'DSCR < 1.25 и есть лимит → встречное предложение',
  R4: 'DSCR ≥ 1.25 и score ≥ 80 → можно одобрять',
  R5: 'Иначе → ручное рассмотрение',
} as const satisfies Record<RuleId, string>

export const providerTexts = {
  EGRUL: 'ЕГРЮЛ',
  EGRIP: 'ЕГРИП',
  FNS: 'ФНС',
  BKI: 'БКИ',
  BANK: 'Выписка по счёту',
} as const satisfies Record<Provider, string>

/** Баллы score по факторам (design.md §3.4): ключ factor_points → подпись и максимум. */
export const scoreFactors = [
  { key: 'dscr', label: 'DSCR', max: 40 },
  { key: 'bki', label: 'Кредитная история', max: 30 },
  { key: 'revenue', label: 'Динамика выручки', max: 15 },
  { key: 'age', label: 'Возраст бизнеса', max: 15 },
] as const

export const termsSourceManagerTexts = {
  MANUAL: 'Введено клиентом',
  RULES_CONFIRMED: 'Распознано правилами, подтверждено клиентом',
  LLM_CONFIRMED: 'Предложено ИИ, подтверждено клиентом',
} as const satisfies Record<Schemas['TermsSource'], string>

export const fieldSourceTexts = {
  MANUAL: 'вручную',
  RULES: 'правила',
  LLM: 'ИИ',
} as const satisfies Record<Schemas['FieldSource'], string>

// Каталог продуктов менеджеру не отдаётся (GET /credit-products — клиентский); названия из seed.
const productNames: Record<string, string> = {
  investment: 'Инвестиционный кредит',
  working_capital: 'Оборотный кредит',
}

export function productName(id: string | null): string {
  if (!id) return '—'
  return productNames[id] ?? id
}

export const legalFormTexts = { LLC: 'ООО', IE: 'ИП' } as const

export const cardTexts = {
  back: 'К очереди',
  inn: 'ИНН',
  legalForm: 'Форма',
  okved: 'ОКВЭД',
  registered: 'Регистрация',
  request: 'Запрос клиента',
  purpose: 'Цель',
  purposeText: 'Своими словами',
  amount: 'Сумма',
  term: 'Срок',
  months: (n: number) => `${n} мес.`,
  product: 'Продукт',
  termsSource: 'Источник условий',
  submitted: 'Отправлена',
  checks: 'Внешние проверки',
  checksEmpty: 'Проверки появятся после отправки заявки',
  fetchedAt: (date: string) => `данные на ${date}`,
  statement: 'Выписка за 12 месяцев',
  revenue: 'Выручка',
  opex: 'Расходы',
  debtSvc: 'Платежи по долгам',
  showTable: 'Показать таблицей',
  showChart: 'Показать графиком',
  month: 'Месяц',
  cfads: 'Свободный денежный поток (cfads)',
  revenueChange: 'Динамика выручки',
  debt: 'Текущие платежи по долгам',
  age: 'Возраст бизнеса',
  historyMonths: 'История по счёту (h)',
  calculation: 'Расчёт',
  skipped: (h: number) => `Недостаточно истории по счёту (${h} мес. из 6) — расчёт не выполнялся`,
  payment: 'Платёж по запросу',
  dscr: 'DSCR',
  dscrTarget: 'Порог 1.25',
  dscrAbove: 'Не ниже порога',
  dscrBelow: 'Ниже порога',
  score: 'Score',
  scoreOf: (points: number, max: number) => `${points} из ${max}`,
  risk: 'Уровень риска',
  limit: 'Лимит на этот срок',
  noLimit: 'Нет — встречное предложение невозможно',
  riskCodes: 'Риски',
  positiveCodes: 'Плюсы',
  proposal: 'Проект решения',
  suggestion: 'Рекомендация системы',
  noProposal: 'Рекомендации нет: заявка ещё не рассчитана',
  blocking: 'Стоп-факторы',
  ruleTrace: 'Как система пришла к рекомендации',
  rule: 'Правило',
  matched: 'Сработало',
  why: 'Почему',
  yes: 'Да',
  no: 'Нет',
  first: 'первое сработавшее',
  allowedActions: 'Доступные действия',
  noActions: 'Действий нет: решение по заявке уже принято',
  decisionOwner: 'Решение принимает менеджер',
  onlyReject: 'Есть стоп-фактор: одобрить или изменить условия нельзя, доступен только отказ',
  history: 'История',
  events: 'События',
  system: 'Система',
  decisions: 'Решения',
  noDecisions: 'Решений пока нет',
  comment: 'Комментарий',
  clientReason: 'Причина для клиента',
  questions: 'Вопросы и ответы',
  answer: 'Ответ клиента',
  noAnswer: 'Клиент ещё не ответил',
  offers: 'Встречные предложения',
  offerStatus: { OPEN: 'Ждёт ответа', ACCEPTED: 'Принято', DECLINED: 'Отклонено' },
  signing: 'Подписание и выдача',
  challenge: (attempts: number) => `Код выдан, попыток ввода: ${attempts}`,
  signed: 'Договор подписан',
  issued: 'Деньги выданы',
} as const

/** Подписи полей сводок внешних источников (ExternalSource.summary). */
/** Поля снимков ext-sim (docs/openapi-ext-sim.json) — подписи для карточки. */
export const sourceSummaryLabels: Record<string, string> = {
  name: 'Название',
  full_name: 'ФИО',
  inn: 'ИНН',
  ogrn: 'ОГРН',
  ogrnip: 'ОГРНИП',
  okved_main: 'ОКВЭД',
  registered_at: 'Регистрация',
  account_masked: 'Счёт',
  from: 'Выписка с',
  to: 'Выписка по',
  transactions_count: 'Операций',
  report_id: 'Номер отчёта',
  obligations: 'Обязательства',
  checked_at: 'Проверено',
  status: 'Статус',
  director: 'Руководитель',
  bankruptcy: 'Банкротство',
  active_account_blocks: 'Блокировки счетов',
  summary_status: 'Кредитная история',
  monthly_payments_total_rub: 'Платежи по кредитам в месяц',
}

export const sourceValueTexts: Record<string, string> = {
  ACTIVE: 'Действует',
  LIQUIDATING: 'В ликвидации',
  LIQUIDATED: 'Ликвидирована',
  CLEAN: 'Без просрочек',
  MINOR: 'Небольшие просрочки',
  SERIOUS: 'Серьёзные просрочки',
  UNKNOWN: 'Нет истории',
  true: 'Да',
  false: 'Нет',
}

export const checksTexts = {
  obligation: (creditor: string, outstanding: string, payment: string) =>
    `${creditor}: остаток ${outstanding}, платёж ${payment} в месяц`,
  none: 'Нет',
  attention: 'Требует внимания',
  ok: 'Без замечаний',
} as const

export const aiTexts = {
  title: 'AI-заключение',
  caption: 'Заключение ИИ-помощника. Не является решением. Числа взяты из расчёта',
  model: (model: string) => `Модель: ${model}`,
  pending: 'Готовим заключение…',
  templateBadge: 'Шаблон',
  /** Причина шаблона вместо ответа модели — `fallback_reason` отчёта. */
  fallback: {
    DISABLED: 'AI отключён — показан шаблон по расчёту',
    TIMEOUT: 'Модель не ответила вовремя — показан шаблон по расчёту',
    UNAVAILABLE: 'Модель недоступна — показан шаблон по расчёту',
    INVALID_OUTPUT: 'Ответ модели не прошёл проверку — показан шаблон по расчёту',
    REPLAY_MISS: 'Нет записанного ответа модели — показан шаблон по расчёту',
  } satisfies Record<FallbackReason, string>,
  fallbackUnknown: 'Показан шаблон по расчёту',
  risks: 'Риски',
  positives: 'Плюсы',
  questions: 'Что уточнить у клиента',
  noFactors: 'Нет',
  meta: (prompt: string, date: string) => `${prompt} · ${date}`,
  useInRequest: 'Использовать в дозапросе',
  regenerate: 'Обновить заключение',
  regenerating: 'Запрашиваем…',
  regenerateTitle: 'Обновить AI-заключение?',
  regenerateDescription:
    'Текущее заключение и оценки к нему будут заменены. Пока готовится новое, карточкой можно пользоваться.',
  regenerateConfirm: 'Обновить',
  cancel: 'Отмена',
  rateTitle: 'Заключение помогло?',
  up: 'Полезно',
  down: 'Не помогло',
  thanks: 'Спасибо, оценка учтена',
  commentLabel: 'Комментарий к оценке',
  commentHint: 'Необязательно: что было не так или чего не хватило',
  commentSend: 'Отправить комментарий',
  commentSent: 'Комментарий сохранён',
} as const

export const MAX_DECISION_TEXT = 1000

export const decisionTexts = {
  title: 'Решение',
  open: {
    APPROVE: 'Одобрить',
    COUNTER_OFFER: 'Предложить другие условия',
    REQUEST_INFO: 'Запросить информацию',
    REJECT: 'Отказать',
  } satisfies Record<ManagerAction, string>,
  dialogTitle: {
    APPROVE: 'Одобрить заявку',
    COUNTER_OFFER: 'Встречное предложение',
    REQUEST_INFO: 'Вопрос клиенту',
    REJECT: 'Отказать в кредите',
  } satisfies Record<ManagerAction, string>,
  dialogDescription: {
    APPROVE: 'Клиенту подготовим договор на запрошенных условиях',
    COUNTER_OFFER:
      'Клиент увидит новые условия и сможет принять их или отказаться. Продукт и ставка не меняются',
    REQUEST_INFO: 'Заявка перейдёт в «Ждут ответа», после ответа клиента вернётся на рассмотрение',
    REJECT: 'Клиент увидит причину простыми словами и что можно сделать',
  } satisfies Record<ManagerAction, string>,
  submit: {
    APPROVE: 'Одобрить',
    COUNTER_OFFER: 'Отправить предложение',
    REQUEST_INFO: 'Отправить вопрос',
    REJECT: 'Отказать',
  } satisfies Record<ManagerAction, string>,
  submitting: 'Отправляем…',
  cancel: 'Отмена',
  done: {
    APPROVE: 'Заявка одобрена',
    COUNTER_OFFER: 'Встречное предложение отправлено клиенту',
    REQUEST_INFO: 'Вопрос отправлен клиенту',
    REJECT: 'Отказ отправлен клиенту',
  } satisfies Record<ManagerAction, string>,
  requested: 'Запрошено',
  comment: 'Комментарий',
  commentHint: 'Виден только сотрудникам банка',
  commentRequired: 'Напишите комментарий',
  approveAgainst: 'Система не рекомендует одобрение — обоснуйте решение в комментарии',
  reason: 'Причина для клиента',
  reasonRequired: 'Выберите причину',
  clientSees: 'Клиент увидит',
  question: 'Вопрос',
  questionHint: 'Клиент ответит в кабинете. Спросите что-то одно и конкретное',
  questionRequired: 'Напишите вопрос',
  aiQuestions: 'Подсказки из AI-заключения',
  conflict:
    'Заявку уже обработал другой менеджер или она изменилась. Обновите данные — введённое останется',
  refresh: 'Обновить',
  clientSeesApprove: (terms: string) => `Заявка одобрена: ${terms}. Договор готов к подписанию`,
  clientSeesOffer: (terms: string) => `Банк предлагает другие условия: ${terms}`,
  clientSeesQuestion: 'Вопрос от банка — ответить нужно в кабинете',
  findTerm: 'Та же сумма, найти срок',
  findingTerm: 'Подбираем срок…',
  termNotFound: (amount: string) => `Ни на одном сроке ${amount} не проходит проверку`,
  termFound: (amount: string, term: number) => `${amount} проходит на ${term} мес.`,
  amount: 'Сумма',
  term: 'Срок, мес.',
  amountHint: (min: string, max: string) => `От ${min} до ${max}`,
  termHint: (min: number, max: number) => `От ${min} до ${max} мес.`,
  amountRequired: 'Введите сумму',
  termRequired: 'Введите срок',
  preview: 'Расчёт на новых условиях',
  previewLoading: 'Считаем…',
  previewError: 'Не удалось посчитать. Измените условия или повторите',
  previewSkipped: 'Расчёт не выполняется: недостаточно данных по счёту',
  previewValid: 'Условия проходят проверку',
  useLimit: (limit: string) => `Взять лимит ${limit}`,
  payment: 'Платёж',
  limitForTerm: 'Лимит на этот срок',
} as const

export const violationTexts = {
  ACTION_NOT_ALLOWED: 'Встречное предложение по этой заявке недоступно',
  AMOUNT_OUT_OF_PRODUCT: 'Сумма вне пределов продукта',
  TERM_OUT_OF_PRODUCT: 'Срок вне пределов продукта',
  AMOUNT_ABOVE_LIMIT: 'Сумма больше лимита на этот срок',
  OFFER_NOT_IMPROVED: 'Срок не изменился — сумма должна быть меньше запрошенной',
  CALCULATION_SKIPPED: 'Расчёт не выполнялся: недостаточно данных по счёту',
} as const satisfies Record<Schemas['OfferViolation'], string>

/** Подсказка причины отказа по стоп-фактору — менеджер может выбрать другую. */
export const stopFactorReason = {
  COMPANY_INACTIVE: 'COMPANY_STATUS',
  APPLICANT_NOT_AUTHORIZED: 'APPLICANT_NOT_AUTHORIZED',
  BANKRUPTCY_PROCEEDING: 'TAX_AUTHORITY_RESTRICTIONS',
  ACCOUNT_BLOCKED_BY_FNS: 'TAX_AUTHORITY_RESTRICTIONS',
  ACCOUNT_HISTORY_INSUFFICIENT: 'INSUFFICIENT_DATA',
} as const satisfies Record<StopFactor, Schemas['ClientReasonCode']>

export const historyTexts = {
  created: 'Черновик создан',
  statusChange: (from: string, to: string) => `${from} → ${to}`,
  statusSet: (to: string) => to,
  by: (name: string) => `· ${name}`,
  contract: (number: string) => `Договор № ${number}`,
  contractStatus: { DRAFT: 'Ждёт подписи', SIGNED: 'Подписан', ISSUED: 'Деньги выданы' },
  signedAt: 'Подписан',
  issuedAt: 'Выдан',
  account: 'Счёт зачисления',
  payment: 'Платёж',
  overpayment: 'Переплата',
  rate: 'Ставка',
  challenges: 'Коды подтверждения',
  challengeUsed: 'использован',
  challengeOpen: 'не использован',
} as const
