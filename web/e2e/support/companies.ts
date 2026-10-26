/** Демо-компании и их запросы — docs/demo-data.md §6 (эталоны берём оттуда, а не из кода). */
export const companies = {
  C1: {
    login: 'director.techservice',
    name: 'ООО «ТехСервис»',
    inn: '0099010012',
    request: { product: 'investment', purpose: 'EQUIPMENT', amount: 2_000_000, term: 36 },
  },
  C2: {
    login: 'director.bakery',
    name: 'ООО «Пекарня Плюс»',
    inn: '0099020010',
    request: { product: 'investment', purpose: 'EQUIPMENT', amount: 3_000_000, term: 36 },
  },
  C3: {
    login: 'ip.sokolova',
    name: 'ИП Соколова А. В.',
    inn: '009903001040',
    request: { product: 'working_capital', purpose: 'WORKING_CAPITAL', amount: 800_000, term: 12 },
  },
  C4: {
    login: 'director.newstart',
    name: 'ООО «Новый Старт»',
    inn: '0099040017',
    request: { product: 'investment', purpose: 'EQUIPMENT', amount: 500_000, term: 24 },
  },
} as const

export type CompanyKey = keyof typeof companies
export type Company = (typeof companies)[CompanyKey]

export const managers = { anna: 'manager.anna', oleg: 'manager.oleg' } as const
export const accountantBakery = 'accountant.bakery'
