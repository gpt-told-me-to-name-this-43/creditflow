import { setupServer } from 'msw/node'
import { handlers } from '@/mocks/handlers.ts'

/**
 * Общий MSW-сервер компонентных тестов: запускается в setup.ts, обработчики сбрасываются
 * после каждого теста. Свой ответ на один тест — `server.use(http.get(…))`.
 */
export const server = setupServer(...handlers)
