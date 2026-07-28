/** Home — direction dispatcher (2026-07-28 rebuild).
 *  Each direction variant is its own lazy chunk, so the un-viewed direction
 *  costs zero bytes on initial load. */
import { lazy, Suspense } from 'react'
import { useDirection } from '../hooks/useDirection'

const HomeCommand = lazy(() => import('../directions/command/HomeCommand'))
const HomeEther = lazy(() => import('../directions/ether/HomeEther'))

export default function Home() {
  const { direction } = useDirection()
  return (
    <Suspense fallback={null}>
      {direction === 'ether' ? <HomeEther /> : <HomeCommand />}
    </Suspense>
  )
}
