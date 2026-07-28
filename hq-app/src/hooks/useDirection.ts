import { useEffect, useState, useCallback } from 'react'

// 2026-07-28 rebuild: the earlier 'onyx-gold' | 'aurora' pass was a token-only
// swap and did not change layout. The real directions are:
//   'command' — Command Grid: status-bar header (no hero), horizontal KPI
//               rail, dense 12-col, mono-forward numerals, glow-line charts,
//               left sidebar. Sharp 10px radii.
//   'ether'   — Ether Ledger: floating pill top-nav (sidebar hidden on the
//               rebuilt pages), big gradient feature card, tinted stat
//               cards, sans-forward type, chunky rounded bars. 20px radii.
export type Direction = 'command' | 'ether'
const KEY = 'jcf-direction'

function initialDirection(): Direction {
  // URL override (?dir=command|ether) — shareable forced direction, and lets
  // headless / screenshot passes pin a direction without touching storage.
  try {
    const q = new URLSearchParams(window.location.search).get('dir')
    if (q === 'command' || q === 'ether') return q
  } catch {
    /* no window/URL */
  }
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'command' || stored === 'ether') return stored
  } catch {
    /* localStorage unavailable */
  }
  return 'command' // default
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
    () => setDirection((d) => (d === 'command' ? 'ether' : 'command')),
    []
  )
  return { direction, toggle, set: setDirection }
}
