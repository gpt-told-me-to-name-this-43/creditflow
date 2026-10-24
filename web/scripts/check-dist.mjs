// Проверяет, что в production-сборку не попал MSW: ни воркер, ни код моков.
// Запускается после `vite build`; сборку на моках (VITE_API_MOCKS=1) не проверяет.
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

if (process.env.VITE_API_MOCKS === '1') process.exit(0)

const dist = new URL('../dist/', import.meta.url).pathname
// Строки из msw/browser и src/mocks, которые переживают минификацию.
const markers = ['mockServiceWorker', '[MSW]', 'creditflow.mock']

const found = readdirSync(dist, { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => join(entry.parentPath, entry.name))
  .flatMap((file) => {
    const text = readFileSync(file, 'utf8')
    return markers.filter((marker) => text.includes(marker)).map((marker) => `${file}: ${marker}`)
  })

if (found.length > 0) {
  console.error('MSW попал в production-сборку:\n' + found.join('\n'))
  process.exit(1)
}
console.log('dist: MSW не найден')
