export const API = '/api/v1'
export const RESET_HEADER = 'X-Test-Reset-Token'
export const DEMO_PASSWORD = 'creditflow-demo'

export const baseURL = () => process.env.E2E_BASE_URL ?? 'http://localhost:8080'

/** Ключ sessionStorage, в котором web хранит сессию (src/lib/auth.ts). */
export const SESSION_KEY = 'creditflow.session'
