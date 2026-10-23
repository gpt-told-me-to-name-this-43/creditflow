import type { components } from '@/api/schema.d.ts'

type Schemas = components['schemas']

// Тексты мастера заявки (/client/applications/new).

export const wizardSteps = [
  { title: 'Потребность', description: 'На что нужны деньги' },
  { title: 'Параметры', description: 'Сумма, срок и цель' },
  { title: 'Кредит', description: 'Подходящее предложение' },
  { title: 'Проверка', description: 'Сводка и отправка' },
] as const

export const needTexts = {
  title: 'Расскажите, на что нужны деньги',
  description:
    'Напишите своими словами — мы сами заполним сумму, срок и цель. Или выберите цель из списка.',
  modeText: 'Своими словами',
  modeManual: 'Выберу сам',
  textLabel: 'Что нужно бизнесу',
  textHint: 'Например, сколько нужно, на какой срок и на что',
  textPlaceholder: 'Нужно 2 млн на 3 года на новую печь',
  examplesLabel: 'Примеры',
  interpret: 'Распознать',
  interpreting: 'Распознаём…',
  fillManually: 'Заполнить вручную',
  recognized: 'Вот что мы поняли из вашего текста',
  recognizedHint: 'Проверьте на следующем шаге — без вашего подтверждения ничего не сохранится',
  nothingRecognized: 'Не получилось ничего распознать. Уточните текст или заполните вручную',
  unavailable:
    'Помощник сейчас недоступен. Заполните параметры вручную — заявка от этого не пострадает',
  manualTitle: 'Выберите цель кредита',
  next: 'Дальше',
} as const

// Чипы-примеры: формулировки под демо-сценарии C1–C7 (docs/demo-data.md, ветка #6).
export const needExamples = [
  'Нужно 2 млн на 3 года на новую печь',
  '3 млн на 36 месяцев на оборудование для цеха',
  '800 тыс. на год, чтобы закупить товар к сезону',
  'Ремонт кафе, 1,5 млн на 2 года',
  'Открыть вторую точку, 4 млн на 5 лет',
  'Предоплата поставщику сырья, 600 тыс. на полгода',
  'Пополнить оборотные средства на 1 млн на 12 месяцев',
] as const

/** Метки полей, заполненных автоматически. */
export const sourceLabels = {
  RULES: {
    label: 'Распознано автоматически',
    tooltip: (matched: string) => `Нашли в вашем тексте: «${matched}»`,
  },
  LLM: {
    label: 'Предложено ИИ',
    tooltip: (matched: string) => `ИИ понял это из слов: «${matched}»`,
  },
  noMatch: 'Проверьте значение перед подтверждением',
} as const

/** Сводный источник условий — подпись под кнопкой подтверждения. */
export const termsSourceTexts = {
  MANUAL: 'Все параметры указаны вами',
  RULES_CONFIRMED: 'Часть параметров мы распознали из текста — проверьте их',
  LLM_CONFIRMED: 'Часть параметров предложил ИИ — проверьте их',
} as const satisfies Record<Schemas['TermsSource'], string>

export const termsTexts = {
  title: 'Проверьте параметры кредита',
  description: 'Поменяйте всё, что нужно. Сохраним, только когда вы подтвердите.',
  purposeLabel: 'Цель',
  amountLabel: 'Сумма',
  amountHint: (min: string, max: string) => `От ${min} до ${max}`,
  termLabel: 'Срок, месяцев',
  termHint: (min: number, max: number) => `От ${min} до ${max} месяцев`,
  confirm: 'Подтвердить параметры',
  saving: 'Сохраняем…',
  back: 'Назад',
  errors: {
    purposeRequired: 'Выберите цель',
    amountRequired: 'Укажите сумму',
    amountTooSmall: (min: string) => `Минимальная сумма — ${min}`,
    amountTooLarge: (max: string) => `Максимальная сумма — ${max}`,
    termRequired: 'Укажите срок в месяцах',
    termOutOfRange: (min: number, max: number) => `Срок — от ${min} до ${max} месяцев`,
  },
} as const

export const productTexts = {
  title: 'Выберите кредит',
  description: 'Показываем, какие кредиты подходят под ваши параметры',
  suitable: 'Подходят',
  unsuitable: 'Не подходят под ваши параметры',
  none: 'Под эти параметры кредитов нет. Измените сумму, срок или цель',
  payment: 'Платёж в месяц',
  rate: 'Ставка',
  amountRange: 'Сумма',
  termRange: 'Срок',
  choose: 'Выбрать',
  chosen: 'Выбран',
  changeTerms: 'Изменить параметры',
  next: 'Дальше',
} as const

/** Почему кредит не подходит — по `unmet_constraints`. */
export const constraintTexts = {
  PURPOSE_NOT_ALLOWED: 'Не выдаётся на эту цель',
  AMOUNT_BELOW_PRODUCT_MIN: 'Сумма меньше минимальной',
  AMOUNT_ABOVE_PRODUCT_MAX: 'Сумма больше максимальной',
  TERM_BELOW_PRODUCT_MIN: 'Срок меньше минимального',
  TERM_ABOVE_PRODUCT_MAX: 'Срок больше максимального',
} as const satisfies Record<Schemas['ProductConstraint'], string>

export const reviewTexts = {
  title: 'Проверьте заявку',
  description: 'Если всё верно — отправьте заявку на рассмотрение',
  purpose: 'Цель',
  purposeText: 'Ваше описание',
  amount: 'Сумма',
  term: 'Срок',
  months: (n: number) => `${n} мес.`,
  product: 'Кредит',
  rate: 'Ставка',
  payment: 'Платёж в месяц',
  overpayment: 'Переплата за весь срок',
  edit: 'Изменить',
  estimate: 'Расчёт предварительный и не является решением банка',
  nextTitle: 'Что будет дальше',
  nextSteps: [
    'Проверим компанию по открытым реестрам и запросим кредитную историю',
    'Менеджер рассмотрит заявку — обычно это занимает несколько минут',
    'Решение появится на странице заявки, обновлять её не нужно',
  ],
  submit: 'Отправить заявку',
  submitting: 'Отправляем…',
  savedRetry: 'Заявка сохранена, но отправить её не удалось. Повторите отправку через минуту',
  incomplete: 'Не хватает данных:',
  goToStep: 'Перейти',
  productNotEligible: 'Выбранный кредит не подходит под параметры заявки. Выберите другой',
} as const

/** Названия полей заявки — для сообщений о незаполненных данных. */
export const fieldTexts: Record<string, { label: string; step: 1 | 2 | 3 | 4 }> = {
  purpose_text: { label: 'описание потребности', step: 1 },
  purpose_code: { label: 'цель', step: 2 },
  requested_amount_rub: { label: 'сумма', step: 2 },
  term_months: { label: 'срок', step: 2 },
  product_id: { label: 'кредит', step: 3 },
  bki_consent_version: { label: 'согласие на запрос кредитной истории', step: 4 },
}
