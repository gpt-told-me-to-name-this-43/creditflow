// Тексты договора, подписания и графика платежей.

export const contractTexts = {
  title: (number: string) => `Договор № ${number}`,
  statusDraft: 'Ожидает подписания',
  statusSigned: (date: string) => `Подписан ${date}`,
  statusIssued: (date: string) => `Деньги зачислены ${date}`,
  amount: 'Сумма кредита',
  term: 'Срок',
  months: (n: number) => `${n} мес.`,
  rate: 'Ставка',
  payment: 'Платёж в месяц',
  overpayment: 'Переплата за весь срок',
  account: 'Счёт зачисления',
  keyTerms: 'Ключевые условия договора',
} as const

export const scheduleTexts = {
  title: 'График платежей',
  number: '№',
  dueDate: 'Дата',
  payment: 'Платёж',
  principal: 'Основной долг',
  interest: 'Проценты',
  balance: 'Остаток долга',
  total: 'Итого',
  showAll: (n: number) => `Показать весь график (${n} платежей)`,
  collapse: 'Свернуть график',
} as const

export const signTexts = {
  title: 'Подписание договора',
  agree: 'Я прочитал(а) договор и согласен(на) с условиями',
  requestCode: 'Получить код',
  requesting: 'Отправляем код…',
  codeSent: 'Мы отправили код подтверждения. Введите его, чтобы подписать договор',
  demoBanner: (code: string) => `Демо: вместо SMS — код ${code}`,
  codeLabel: 'Код подтверждения',
  codeHint: '6 цифр',
  expiresIn: (time: string) => `Код действует ещё ${time}`,
  expired: 'Код больше не действует. Получите новый',
  attemptsLeft: (n: number) =>
    `Осталось ${n} ${n === 1 ? 'попытка' : n >= 2 && n <= 4 ? 'попытки' : 'попыток'}`,
  wrongCode: (n: number) => `Неверный код. ${signTexts.attemptsLeft(n)}`,
  tooManyAttempts: 'Код введён неверно слишком много раз. Получите новый код',
  tooManyCodes: (seconds: number) =>
    `Слишком много запросов кода. Попробуйте через ${Math.ceil(seconds / 60)} мин.`,
  newCode: 'Получить новый код',
  sign: 'Подписать договор',
  signing: 'Подписываем…',
} as const
