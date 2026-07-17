import { NavLink, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import type { ReactNode } from 'react'
import BackgroundOrbs from './BackgroundOrbs'
import { useLiveClock } from '../hooks/useLiveClock'
import { liveCount } from '../data/agentConfig'

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
        background: 'rgba(7,8,15,0.55)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        zIndex: 10,
      }}
    >
      {/* Logo + wordmark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 30, paddingLeft: 4 }}>
        <img className="logo-img" src="/logo-jcf.png" alt="JCF" style={{ width: 38, height: 38 }} />
        <div style={{ lineHeight: 1.1 }}>
          <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: '0.02em' }}>JCF HQ</div>
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
                  background: isActive ? 'rgba(212,168,67,0.10)' : 'transparent',
                  border: isActive ? '0.5px solid var(--gold-border)' : '0.5px solid transparent',
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

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  return (
    <>
      <BackgroundOrbs />
      <div className="app-shell">
        <Sidebar />
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
