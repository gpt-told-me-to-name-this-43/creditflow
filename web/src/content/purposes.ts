import type { PurposeCode } from '@/api/enums.ts'

interface PurposeText {
  label: string
  /** Пример для карточки цели в ручном режиме. */
  example: string
}

export const purposeTexts = {
  EQUIPMENT: { label: 'Оборудование', example: 'Печь, станок, холодильная витрина' },
  RENOVATION: { label: 'Ремонт помещения', example: 'Ремонт цеха, кафе или офиса' },
  BUSINESS_EXPANSION: { label: 'Расширение бизнеса', example: 'Вторая точка, новый филиал' },
  INVENTORY: { label: 'Закупка товара', example: 'Запас к сезону, большая партия' },
  SUPPLIERS: { label: 'Оплата поставщикам', example: 'Предоплата за сырьё или товар' },
  WORKING_CAPITAL: {
    label: 'Пополнение оборотных средств',
    example: 'Зарплаты, аренда, кассовый разрыв',
  },
} as const satisfies Record<PurposeCode, PurposeText>
