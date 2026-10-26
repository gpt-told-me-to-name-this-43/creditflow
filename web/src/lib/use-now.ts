import { useEffect, useState } from 'react'

/** Текущее время, обновляется раз в `intervalMs`, пока `active`: таймеры и «ждёт N мин». */
export function useNow(intervalMs: number, active = true) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [active, intervalMs])
  return now
}
