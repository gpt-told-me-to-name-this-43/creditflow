import { describe, expect, it } from 'vitest'
import {
  compareMoney,
  formatMoney,
  formatRate,
  fromKopecks,
  groupRubles,
  normalizeRubles,
  rublesToNumber,
  subtractMoney,
  sumMoney,
  toKopecks,
  wholeRubles,
} from './money.ts'

const nbsp = (s: string) => s.replaceAll(' ', ' ')

describe('formatMoney', () => {
  it('форматирует сумму из API с копейками', () => {
    expect(formatMoney('2340000.00')).toBe(nbsp('2 340 000,00 ₽'))
    expect(formatMoney('91356.79')).toBe(nbsp('91 356,79 ₽'))
  })

  it('принимает целые рубли и одну цифру копеек', () => {
    expect(formatMoney('3000000')).toBe(nbsp('3 000 000,00 ₽'))
    expect(formatMoney('0.5')).toBe(nbsp('0,50 ₽'))
  })

  it('kopecks: false скрывает только нулевые копейки', () => {
    expect(formatMoney('3000000.00', { kopecks: false })).toBe(nbsp('3 000 000 ₽'))
    expect(formatMoney('100.01', { kopecks: false })).toBe(nbsp('100,01 ₽'))
  })

  it('не теряет копейки на больших суммах', () => {
    expect(formatMoney('90071992547409.93')).toBe(nbsp('90 071 992 547 409,93 ₽'))
  })

  it('показывает знак минус', () => {
    expect(formatMoney('-1500.00')).toBe(nbsp('−1 500,00 ₽'))
  })

  it('бросает на нечисловой строке', () => {
    expect(() => formatMoney('1e6')).toThrow()
    expect(() => formatMoney('12.345')).toThrow()
    expect(() => formatMoney('')).toThrow()
  })
})

describe('арифметика в копейках', () => {
  it('toKopecks/fromKopecks туда и обратно', () => {
    expect(toKopecks('117698.56')).toBe(11769856n)
    expect(fromKopecks(11769856n)).toBe('117698.56')
    expect(fromKopecks(-5n)).toBe('-0.05')
  })

  it('compareMoney сравнивает без потери точности', () => {
    expect(compareMoney('0.10', '0.1')).toBe(0)
    expect(compareMoney('2340000.00', '3000000.00')).toBe(-1)
    expect(compareMoney('9007199254740993.00', '9007199254740992.00')).toBe(1)
  })

  it('subtractMoney считает разницу двух сумм', () => {
    expect(subtractMoney('1288852.44', '1237145.04')).toBe('51707.40')
    expect(subtractMoney('0.10', '0.30')).toBe('-0.20')
  })
})

describe('ввод суммы в рублях', () => {
  it('normalizeRubles оставляет только цифры без ведущих нулей', () => {
    expect(normalizeRubles('3 000 000 ₽')).toBe('3000000')
    expect(normalizeRubles('007')).toBe('7')
    expect(normalizeRubles('abc')).toBe('')
    expect(normalizeRubles('1234567890123456')).toBe('123456789012')
  })

  it('groupRubles разбивает на разряды неразрывными пробелами', () => {
    expect(groupRubles('3000000')).toBe(nbsp('3 000 000'))
    expect(groupRubles('999')).toBe('999')
  })

  it('wholeRubles переводит сумму API в цифры формы', () => {
    expect(wholeRubles('3000000.00')).toBe('3000000')
    expect(wholeRubles('2340000')).toBe('2340000')
  })

  it('rublesToNumber — точное целое для тела запроса', () => {
    expect(rublesToNumber('3000000')).toBe(3_000_000)
    expect(rublesToNumber('999999999999')).toBe(999_999_999_999)
    expect(() => rublesToNumber('')).toThrow()
    expect(() => rublesToNumber('1.5')).toThrow()
  })
})

describe('formatRate', () => {
  it('убирает нулевые знаки после запятой', () => {
    expect(formatRate('24.00')).toBe(nbsp('24 % годовых'))
    expect(formatRate('24.50')).toBe(nbsp('24,5 % годовых'))
    expect(formatRate('25')).toBe(nbsp('25 % годовых'))
  })
})

describe('sumMoney', () => {
  it('складывает до копейки', () => {
    expect(sumMoney(['0.10', '0.20', '0.30'])).toBe('0.60')
    expect(sumMoney(['117698.56', '117698.56', '117698.59'])).toBe('353095.71')
    expect(sumMoney([])).toBe('0.00')
  })
})
