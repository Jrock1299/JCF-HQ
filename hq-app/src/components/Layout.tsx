import { NavLink, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import type { ReactNode } from 'react'
import BackgroundOrbs from './BackgroundOrbs'
import HunchoAssistant from './HunchoAssistant'
import { useLiveClock } from '../hooks/useLiveClock'
import { useTheme } from '../hooks/useTheme'
import { useDirection } from '../hooks/useDirection'
import { useEditMode } from '../edit/EditModeContext'
import { liveCount } from '../data/agentConfig'
import { EtherNav } from '../directions/shared'

function ControlCluster() {
  const { theme, toggle } = useTheme()
  const { direction, toggle: toggleDirection } = useDirection()
  const { editing, toggle: toggleEdit } = useEditMode()
  return (
    <div className="control-cluster">
      <button
        className="control-btn"
        onClick={toggleEdit}
        title={editing ? 'Done editing' : 'Edit values'}
        aria-label="Toggle edit mode"
        aria-pressed={editing}
        style={
          editing
            ? { color: 'var(--gold-hi)', borderColor: 'var(--gold-border)', background: 'rgba(212,168,67,0.14)', boxShadow: '0 0 14px -3px rgba(212,168,67,0.5)' }
            : undefined
        }
      >
        {editing ? '✓' : '✎'}
      </button>
      <button
        className="control-btn"
        onClick={toggleDirection}
        title={direction === 'command' ? 'Switch to Ether Ledger' : 'Switch to Command Grid'}
        aria-label="Toggle design direction"
        aria-pressed={direction === 'ether'}
      >
        {direction === 'command' ? '⌗' : '◍'}
      </button>
      <button className="control-btn" onClick={toggle} title={theme === 'dark' ? 'Switch to light' : 'Switch to dark'} aria-label="Toggle theme">
        {theme === 'dark' ? '☀' : '☾'}
      </button>
      <button className="control-btn" title="Notifications" aria-label="Notifications" style={{ position: 'relative' }}>
        <span style={{ fontSize: 15 }}>🔔</span>
        <span style={{ position: 'absolute', top: 8, right: 9, width: 6, height: 6, borderRadius: 50, background: 'var(--gold)', boxShadow: '0 0 6px var(--gold)' }} />
      </button>
    </div>
  )
}

const NAV = [
  { to: '/', label: 'Home', icon: '◉' },
  { to: '/trading', label: 'Trading', icon: '⚔' },
  { to: '/finances', label: 'Finances', icon: '◈' },
  { to: '/intelligence', label: 'Intelligence', icon: '⟁' },
  { to: '/hub', label: 'Agent Hub', icon: '❖' },
  { to: '/agents', label: 'Agents', icon: '⬡' },
]

function Sidebar() {
  const now = useLiveClock()
  const clock = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })
  const date = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })

  return (
    <aside
      style={{
        position: 'fixed',
        left: 0,
        top: 0,
        bottom: 0,
        width: 'var(--sidebar-w)',
        display: 'flex',
        flexDirection: 'column',
        padding: '22px 16px',
        borderRight: '0.5px solid var(--glass-border)',
        background: 'var(--panel-bg)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        zIndex: 10,
      }}
    >
      {/* Logo + wordmark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 30, paddingLeft: 4 }}>
        <img className="logo-img" src="/logo-jcf.png" alt="JCF" style={{ width: 38, height: 38 }} />
        <div style={{ lineHeight: 1.1 }}>
          <div className="iceland" style={{ fontSize: 22, letterSpacing: '0.04em' }}>JCF HQ</div>
          <div className="mono" style={{ fontSize: 8, color: 'var(--text-mute)', letterSpacing: '0.22em', marginTop: 2 }}>
            COMMAND CENTER
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} style={{ textDecoration: 'none' }}>
            {({ isActive }) => (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '10px 12px',
                  borderRadius: 10,
                  fontSize: 14,
                  fontWeight: isActive ? 600 : 400,
                  color: isActive ? 'var(--gold-hi)' : 'var(--text-dim)',
                  background: isActive ? 'rgba(212,168,67,0.12)' : 'transparent',
                  border: isActive ? '0.5px solid var(--gold-border)' : '0.5px solid transparent',
                  boxShadow: isActive ? '0 0 16px -2px rgba(212,168,67,0.35)' : 'none',
                  transition: 'all 0.18s ease',
                }}
              >
                <span style={{ fontSize: 13, width: 16, textAlign: 'center', opacity: isActive ? 1 : 0.6 }}>{n.icon}</span>
                {n.label}
              </div>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer: clock + live badge */}
      <div style={{ marginTop: 16, paddingTop: 16, borderTop: '0.5px solid var(--glass-border)' }}>
        <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-hi)', letterSpacing: '0.02em' }}>
          {clock}
        </div>
        <div className="mono-meta" style={{ marginTop: 2 }}>{date}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 12 }}>
          <span className="dot dot-live" />
          <span className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            {liveCount} agents live
          </span>
        </div>
      </div>
    </aside>
  )
}

// Routes rebuilt in the two-direction system. Under direction=ether these
// swap the sidebar for the floating pill top-nav — a real structural
// difference between the directions, not a reskin. Non-rebuilt routes
// (finances, hub, agents) keep the sidebar under BOTH directions so
// navigation never breaks.
const ETHER_REBUILT = new Set(['/', '/trading', '/intelligence'])

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { direction } = useDirection()
  const etherMode = direction === 'ether' && ETHER_REBUILT.has(location.pathname)
  return (
    <>
      <BackgroundOrbs />
      <ControlCluster />
      <HunchoAssistant />
      <div className={`app-shell${etherMode ? ' app-shell-ether' : ''}`}>
        {etherMode ? <EtherNav /> : <Sidebar />}
        <main className="main-scroll">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </>
  )
}
