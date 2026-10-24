// Все ключи TanStack Query — только отсюда. Префиксные ключи (`applications.all`)
// инвалидируют всё дерево: и список, и карточки.
export const queryKeys = {
  health: ['health'] as const,
  me: ['me'] as const,
  company: ['company'] as const,
  consentTexts: ['consents', 'texts'] as const,
  demoAccounts: ['auth', 'demo-accounts'] as const,
  creditProducts: (params: { purpose?: string; amount?: number; term?: number }) =>
    ['credit-products', params] as const,
  applications: {
    all: ['applications'] as const,
    detail: (id: string) => ['applications', id] as const,
    contract: (id: string) => ['applications', id, 'contract'] as const,
  },
}
