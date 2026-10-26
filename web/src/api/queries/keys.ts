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
  // Кабинет менеджера: префикс `manager.all` обновляет очередь, сводку и карточки разом.
  manager: {
    all: ['manager'] as const,
    queue: (status: string) => ['manager', 'queue', status] as const,
    detail: (id: string) => ['manager', 'applications', id] as const,
    aiReport: (id: string) => ['manager', 'applications', id, 'ai-report'] as const,
    offerPreview: (id: string, amount: number, term: number) =>
      ['manager', 'applications', id, 'offer-preview', amount, term] as const,
    stats: ['manager', 'stats'] as const,
  },
}
