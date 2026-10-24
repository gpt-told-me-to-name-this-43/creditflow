/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `1` — API на моках MSW (src/mocks), бэкенд не нужен. */
  readonly VITE_API_MOCKS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
