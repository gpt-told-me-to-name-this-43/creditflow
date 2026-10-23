import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { isValidInn } from '@/lib/inn.ts'
import {
  bindCompany,
  db,
  ISSUE_DELAY_MS,
  normalizeFullName,
  resetDb,
  restoreDb,
  REVIEW_DELAY_MS,
  signApplication,
  snapshotDb,
  submitApplication,
} from './db.ts'
import { setScenario } from './scenarios.ts'

function userId(login: string) {
  const user = db.findUserByEmail(`${login}@creditflow.demo`)
  if (!user) throw new Error(login)
  return user.id
}

function boundApplication() {
  const result = bindCompany(userId('director.techservice'), '0099010012')
  expect(result.ok).toBe(true)
  const user = db.findUser(userId('director.techservice'))
  if (!user) throw new Error('нет пользователя')
  return Object.assign(db.createApplication(user), {
    purpose_code: 'EQUIPMENT',
    requested_amount_rub: '3000000.00',
    term_months: 36,
    product_id: 'investment',
  } as const)
}

describe('демо-данные', () => {
  it('ИНН учёток и реестра проходят проверку контрольных цифр', () => {
    for (const login of ['director.techservice', 'ip.sokolova', 'accountant.bakery']) {
      const inn = db.findUser(userId(login))?.person_inn
      expect(inn && isValidInn(inn)).toBe(true)
    }
    expect(isValidInn('0099010012')).toBe(true)
  })

  it('ФИО сравниваются без учёта регистра, ё и лишних пробелов', () => {
    expect(normalizeFullName('  Соколова  Алёна ВИКТОРОВНА ')).toBe('соколова алена викторовна')
  })
})

describe('привязка компании', () => {
  it('руководитель привязывает свою компанию', () => {
    const result = bindCompany(userId('director.bakery'), '0099020010')
    expect(result).toMatchObject({
      ok: true,
      company: { name: 'ООО «Пекарня Плюс»', legal_form: 'LLC' },
    })
    expect(db.findUser(userId('director.bakery'))?.company_id).toBe(result.ok && result.company.id)
  })

  it('ИП привязывает себя', () => {
    const result = bindCompany(userId('ip.sokolova'), '009903001040')
    expect(result).toMatchObject({ ok: true, company: { legal_form: 'IE' } })
  })

  it('бухгалтер не может привязать компанию', () => {
    expect(bindCompany(userId('accountant.bakery'), '0099020010')).toEqual({
      ok: false,
      status: 403,
      code: 'APPLICANT_NOT_AUTHORIZED',
    })
  })

  it('ошибки: неверный ИНН, нет в реестре, уже привязана', () => {
    expect(bindCompany(userId('director.vector'), '123')).toMatchObject({ code: 'INVALID_INN' })
    expect(bindCompany(userId('director.vector'), '0099050016')).toMatchObject({
      code: 'INVALID_INN',
    })
    expect(bindCompany(userId('director.vector'), '0099999999')).toMatchObject({
      code: 'COMPANY_NOT_IN_REGISTRY',
    })
    const first = bindCompany(userId('director.vector'), '0099050015')
    expect(bindCompany(userId('director.vector'), '0099050015')).toEqual(first)
    expect(bindCompany(userId('director.vector'), '0099060013')).toMatchObject({
      status: 409,
      code: 'USER_ALREADY_BOUND',
    })
    expect(bindCompany(userId('director.sklad'), '0099050015')).toMatchObject({
      status: 403,
      code: 'APPLICANT_NOT_AUTHORIZED',
    })
  })

  it('resetDb возвращает исходное состояние', () => {
    bindCompany(userId('director.sklad'), '0099060013')
    resetDb()
    expect(db.findUser(userId('director.sklad'))?.company_id).toBeNull()
  })
})

describe('смена статусов по таймеру', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('по умолчанию заявка ждёт менеджера', () => {
    const application = boundApplication()
    submitApplication(application)
    vi.advanceTimersByTime(REVIEW_DELAY_MS * 10)
    expect(application.status).toBe('UNDER_REVIEW')
  })

  it('сценарий решает заявку через паузу, ревизия и таймлайн растут', () => {
    setScenario('offer')
    const application = boundApplication()
    submitApplication(application)
    expect(application).toMatchObject({ status: 'UNDER_REVIEW', revision: 2 })

    vi.advanceTimersByTime(REVIEW_DELAY_MS)
    expect(application).toMatchObject({ status: 'COUNTER_OFFER', revision: 3 })
    expect(application.offer).toEqual({
      amount_rub: '2340000.00',
      term_months: 36,
      annual_rate_pct: '24.00',
    })
    expect(db.listEvents(application.id).map((event) => event.to_status)).toEqual([
      'DRAFT',
      'UNDER_REVIEW',
      'COUNTER_OFFER',
    ])
  })

  it('после подписи средства зачисляются через несколько секунд', () => {
    const application = boundApplication()
    signApplication(application)
    expect(application.status).toBe('SIGNED')
    vi.advanceTimersByTime(ISSUE_DELAY_MS)
    expect(application.status).toBe('ISSUED')
  })

  it('resetDb отменяет отложенные переходы', () => {
    setScenario('approve')
    const application = boundApplication()
    submitApplication(application)
    resetDb()
    vi.advanceTimersByTime(REVIEW_DELAY_MS)
    expect(application.status).toBe('UNDER_REVIEW')
  })

  it('снимок переживает «перезагрузку»: данные и отложенный переход на месте', () => {
    setScenario('approve')
    const application = boundApplication()
    submitApplication(application)
    const snapshot = snapshotDb()
    resetDb()
    restoreDb(snapshot)
    vi.advanceTimersByTime(REVIEW_DELAY_MS)
    expect(db.findApplication(application.id)?.status).toBe('APPROVED')
    expect(db.findUser(userId('director.techservice'))?.company_id).not.toBeNull()
  })
})
