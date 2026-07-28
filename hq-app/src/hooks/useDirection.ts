import { useEffect, useState, useCallback } from 'react'

export type Direction = 'onyx-gold' | 'aurora'
const KEY = 'jcf-direction'

function initialDirection(): Direction {
  // URL override (?dir=onyx-gold|aurora) — shareable forced direction, and lets
  // headless / screenshot passes pin a direction without touching storage.
  try {
    const q = new URLSearchParams(window.location.search).get('dir')
    if (q === 'onyx-gold' || q === 'aurora') return q
  } catch {
    /* no window/URL */
  }
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'onyx-gold' || stored === 'aurora') return stored
  } catch {
    /* localStorage unavailable */
  }
  return 'onyx-gold' // default — the current identity, refined
}

/** Applies `data-direction` to <html>, persists to localStorage. Composes
 *  with `data-theme` so components read four skin combinations. See
 *  hq-app/src/styles/directions.css for the token blocks and
 *  hq-app/DESIGN_REDESIGN.md for the direction rationale. */
export function useDirection(): { direction: Direction; toggle: () => void; set: (d: Direction) => void } {
  const [direction, setDirection] = useState<Direction>(initialDirection)

  useEffect(() => {
    document.documentElement.setAttribute('data-direction', direction)
    try {
      localStorage.setItem(KEY, direction)
    } catch {
      /* ignore */
    }
  }, [direction])

  const toggle = useCallback(
    () => setDirection((d) => (d === 'onyx-gold' ? 'aurora' : 'onyx-gold')),
    []
  )
  return { direction, toggle, set: setDirection }
}
