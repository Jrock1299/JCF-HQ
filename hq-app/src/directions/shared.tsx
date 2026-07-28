/** Shared primitives for the two design directions (2026-07-28 rebuild).
 *
 * Kept deliberately small: the point of the two-direction architecture is
 * that the page variants OWN their layout — this file holds only what both
 * genuinely share (feed staleness, formatting, the Ether pill nav, the
 * Command status strip). If a helper starts accumulating per-direction
 * branches, move it into the direction folder instead. */
import { NavLink } from 'react-router-dom'
import { useLiveClock, greeting } from '../hooks/useLiveClock'
import { feedAgeDays, feedIsStale } from '../hooks/useHQData'

// ── Feed staleness UI ─────────────────────────────────────────────────

export function FeedAge({ iso, label }: { iso: string | null | undefined; label?: string }) {
  const d = feedAgeDays(iso)
  const stale = feedIsStale(iso)
  const text = d == null ? 'no timestamp' : d < 1 ? 'fresh' : `${Math.floor(d)}d old`
  return (
    <span
      className="mono"
      style={{
        fontSize: 9,
        letterSpacing: '0.08em',
        padding: '2px 7px',
        borderRadius: 'var(--dir-radius-inline)',
        color: stale ? 'var(--red)' : 'var(--green)',
        background: stale ? 'rgba(239,68,68,0.10)' : 'rgba(34,197,94,0.10)',
        border: `1px solid ${stale ? 'rgba(239,68,68,0.25)' : 'rgba(34,197,94,0.2)'}`,
      }}
    >
      {label ? `${label} · ` : ''}{text}
    </span>
  )
}

/** Wraps a feed section: if the feed is stale/absent, renders an honest
 *  offline panel INSTEAD of months-old content. This is the frontend twin of
 *  the backend's STALE_DATA verdict — never render fiction. */
export function StaleGuard({
  iso, feedName, children,
}: {
  iso: string | null | undefined
  feedName: string
  children: React.ReactNode
}) {
  if (!feedIsStale(iso)) return <>{children}</>
  const d = feedAgeDays(iso)
  return (
    <div
      style={{
        padding: '22px 20px',
        borderRadius: 'var(--dir-radius-card)',
        border: '1px dashed rgba(239,68,68,0.3)',
        background: 'rgba(239,68,68,0.04)',
      }}
    >
      <div className="mono" style={{ fontSize: 11, color: 'var(--red)', letterSpacing: '0.1em' }}>
        FEED OFFLINE — {feedName}
      </div>
      <div className="soft" style={{ fontSize: 12.5, color: 'var(--text-dim)', marginTop: 6, lineHeight: 1.5 }}>
        {d == null
          ? 'No timestamp on this feed. Not rendering unverifiable data.'
          : `Newest record is ${Math.floor(d)} days old. Content hidden rather than shown as current.`}
      </div>
    </div>
  )
}

// ── Ether Ledger: floating pill top-nav ───────────────────────────────
// Replaces the sidebar on the rebuilt pages under direction=ether — one of
// the real structural differences between the two directions (ref: the
// "ethereal" dashboard's floating pill).

const ETHER_NAV = [
  { to: '/', label: 'Home' },
  { to: '/trading', label: 'Trading' },
  { to: '/intelligence', label: 'Intel' },
  { to: '/finances', label: 'Finances' },
  { to: '/agents', label: 'Agents' },
]

export function EtherNav() {
  return (
    <nav className="ether-nav" aria-label="Primary">
      <img src="/logo-jcf.png" alt="JCF" style={{ width: 30, height: 30, marginRight: 6 }} />
      {ETHER_NAV.map((n) => (
        <NavLink key={n.to} to={n.to} end={n.to === '/'}>
          {({ isActive }) => (
            <span className={`ether-nav-pill${isActive ? ' ether-nav-active' : ''}`}>{n.label}</span>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

export function EtherGreeting() {
  const now = useLiveClock()
  return (
    <div style={{ margin: '6px 0 22px 2px' }}>
      <div style={{ fontFamily: 'var(--font-body)', fontWeight: 600, fontSize: 40, letterSpacing: '-0.02em', lineHeight: 1.05 }}>
        {greeting(now)}, Jase
      </div>
    </div>
  )
}

// ── Command Grid: status strip (replaces the hero entirely) ───────────
// The command bridge doesn't greet you — it reports state. One-line strip:
// date · UTC clock · operator. Iceland stays retired here (logo only, per
// DESIGN.md §4).

export function CommandStatusBar({ right }: { right?: React.ReactNode }) {
  const now = useLiveClock()
  const utc = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' })
  const date = now.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', timeZone: 'UTC' }).toUpperCase()
  return (
    <div className="cmd-statusbar">
      <span className="mono" style={{ color: 'var(--dir-accent)', fontSize: 11, letterSpacing: '0.14em' }}>
        {'// '}{date} · {utc} UTC
      </span>
      <span className="mono" style={{ color: 'var(--text-mute)', fontSize: 11, letterSpacing: '0.1em' }}>
        OPERATOR: JASE
      </span>
      {right}
    </div>
  )
}
