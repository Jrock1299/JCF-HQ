/** Trading — direction dispatcher (2026-07-28 rebuild). */
import { lazy, Suspense } from 'react'
import { useDirection } from '../hooks/useDirection'

const TradingCommand = lazy(() => import('../directions/command/TradingCommand'))
const TradingEther = lazy(() => import('../directions/ether/TradingEther'))

export default function Trading() {
  const { direction } = useDirection()
  return (
    <Suspense fallback={null}>
      {direction === 'ether' ? <TradingEther /> : <TradingCommand />}
    </Suspense>
  )
}
