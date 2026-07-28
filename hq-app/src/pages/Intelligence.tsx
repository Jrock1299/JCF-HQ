/** Intelligence — direction dispatcher (2026-07-28 rebuild).
 *
 *  DATA NOTE: both variants dropped morning_report.json — it fossilised at
 *  2026-04-15 (Oracle picks, "Crisp & Blade") and its cron is #HOLD. The
 *  rebuilt variants read only fresh feeds and stale-guard every one. */
import { lazy, Suspense } from 'react'
import { useDirection } from '../hooks/useDirection'

const IntelCommand = lazy(() => import('../directions/command/IntelCommand'))
const IntelEther = lazy(() => import('../directions/ether/IntelEther'))

export default function Intelligence() {
  const { direction } = useDirection()
  return (
    <Suspense fallback={null}>
      {direction === 'ether' ? <IntelEther /> : <IntelCommand />}
    </Suspense>
  )
}
