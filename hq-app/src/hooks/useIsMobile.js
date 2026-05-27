import { useState, useEffect } from 'react'

/**
 * Returns true when viewport width is ≤ 768px.
 * Updates reactively on resize.
 */
export function useIsMobile() {
  const [mobile, setMobile] = useState(() => window.innerWidth <= 768)
  useEffect(() => {
    const fn = () => setMobile(window.innerWidth <= 768)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return mobile
}

/**
 * Returns true when viewport width is ≤ 480px (very small / iPhone SE).
 */
export function useIsSmall() {
  const [small, setSmall] = useState(() => window.innerWidth <= 480)
  useEffect(() => {
    const fn = () => setSmall(window.innerWidth <= 480)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return small
}
