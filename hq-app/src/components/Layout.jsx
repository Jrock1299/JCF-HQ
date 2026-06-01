import { useState } from 'react'

// ── Navigation config ──────────────────────────────────────────────────
const NAV_SECTIONS = [
  {
    label: 'Overview',
    items: [
      { id: 'dashboard',    label: 'Dashboard',      icon: '⌂' },
      { id: 'portfolio',    label: 'Portfolio',      icon: '◈' },
      { id: 'intelligence', label: 'Intelligence',   icon: '◎' },
    ],
  },
  {
    label: 'Markets',
    items: [
      { id: 'trading',      label: 'Trading',        icon: '↗' },
    ],
  },
  {
    label: 'Operations',
    items: [
      { id: 'agents',       label: 'Agents',         icon: '◆' },
      { id: 'projects',     label: 'Projects',       icon: '▣' },
      { id: 'investing',    label: 'Investing',      icon: '◇' },
      { id: 'timeline',     label: 'Timeline',       icon: '≡' },
      { id: 'basketball',   label: 'Basketball',     icon: '◐' },
    ],
  },
]

// Bottom-nav items shown on mobile (most important 5, rest in sheet)
const MOBILE_PRIMARY = ['dashboard', 'portfolio', 'agents', 'projects', 'trading']

export default function Layout({ activeTab, onTabChange, demoMode, children }) {
  const [moreOpen, setMoreOpen] = useState(false)

  const allItems = NAV_SECTIONS.flatMap(s => s.items)
  const primaryItems = MOBILE_PRIMARY.map(id => allItems.find(i => i.id === id)).filter(Boolean)
  const secondaryItems = allItems.filter(i => !MOBILE_PRIMARY.includes(i.id))

  function handleNav(id) {
    onTabChange(id)
    setMoreOpen(false)
  }

  return (
    <div className="flex min-h-screen">

      {/* ── Desktop sidebar ─────────────────────────────────────────── */}
      <aside
        className="hidden md:flex flex-col w-sidebar min-h-screen fixed top-0 left-0 z-[100]"
        style={{
          background: 'rgba(7,12,26,0.98)',
          borderRight: '1px solid rgba(201,168,76,0.1)',
          backdropFilter: 'blur(20px)',
        }}
      >
        {/* Logo */}
        <div
          className="flex flex-col items-center"
          style={{ padding: '24px 20px', borderBottom: '1px solid rgba(201,168,76,0.08)' }}
        >
          <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{
              position: 'absolute',
              inset: '-10px',
              background: 'radial-gradient(ellipse at center, rgba(212,168,67,0.18) 0%, transparent 70%)',
              borderRadius: '50%',
              pointerEvents: 'none',
            }} />
            <img
              src="/logo-jcf.png"
              alt="JCF"
              style={{ height: 60, width: 'auto', display: 'block', position: 'relative' }}
            />
          </div>
          <div style={{
            marginTop: 10,
            fontFamily: "'Playfair Display', serif",
            fontSize: 14,
            color: '#d4a843',
            letterSpacing: '1px',
            fontWeight: 600,
          }}>
            JCF MGMT
          </div>
          <div style={{
            marginTop: 3,
            fontSize: 10,
            color: '#64748b',
            letterSpacing: '3px',
            textTransform: 'uppercase',
          }}>
            HQ · Mission Control
          </div>
        </div>

        {/* Greeting / demo badge */}
        <div className="px-5 py-3.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
          {demoMode && (
            <span className="pill pill-gold mb-2 inline-block">Demo Mode</span>
          )}
          <div className="text-[11px] text-dim leading-relaxed">
            Good day, <span className="text-gold font-semibold">JCF</span>
          </div>
        </div>

        {/* Nav sections */}
        <nav className="flex-1 px-2.5 py-2.5 overflow-y-auto">
          {NAV_SECTIONS.map(section => (
            <div key={section.label}>
              <div className="text-[7px] tracking-[3px] uppercase text-muted px-2.5 pt-2.5 pb-1">
                {section.label}
              </div>
              {section.items.map(item => (
                <button
                  key={item.id}
                  onClick={() => onTabChange(item.id)}
                  className={[
                    'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer',
                    'text-xs mb-0.5 transition-all duration-150 border text-left',
                    activeTab === item.id
                      ? 'bg-gold/[0.08] text-gold border-gold/[0.15]'
                      : 'text-muted border-transparent hover:bg-white/[0.04] hover:text-dim',
                  ].join(' ')}
                >
                  <span className="text-sm w-[18px] text-center">{item.icon}</span>
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        {/* Footer — live status */}
        <div className="px-5 py-3.5" style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <div className="flex items-center gap-2">
            <span className="status-dot" />
            <span className="text-[9px] tracking-[2px] uppercase text-muted">Systems Online</span>
          </div>
        </div>
      </aside>

      {/* ── Mobile top bar ───────────────────────────────────────────── */}
      <header
        className="md:hidden fixed top-0 left-0 right-0 z-[200] flex items-center justify-between px-4 py-3"
        style={{
          background: 'rgba(7,12,26,0.98)',
          borderBottom: '1px solid rgba(201,168,76,0.12)',
          backdropFilter: 'blur(20px)',
        }}
      >
        <div className="flex items-center gap-2.5">
          <img
            src="/logo-jcf.png"
            alt="JCF"
            style={{ height: 28, width: 'auto' }}
          />
          <span className="text-[8px] tracking-[3px] uppercase text-muted">HQ · Mission Control</span>
        </div>
        <div className="flex items-center gap-2">
          {demoMode && <span className="pill pill-gold">Demo</span>}
          <span className="status-dot" />
        </div>
      </header>

      {/* ── Main content area ────────────────────────────────────────── */}
      <main
        className="flex-1 md:ml-[220px] relative z-[1] min-h-screen
                   pt-[68px] pb-[80px] px-4
                   md:pt-9 md:pb-9 md:px-8"
      >
        <div className="max-w-[1060px] animate-fade-in">
          {children}
        </div>
      </main>

      {/* ── DEMO MODE badge — fixed top-right ────────────────────────── */}
      {demoMode && (
        <div
          style={{
            position: 'fixed',
            top: 12,
            right: 12,
            zIndex: 9999,
            padding: '4px 12px',
            borderRadius: 6,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: '2px',
            textTransform: 'uppercase',
            color: '#c9a84c',
            background: 'rgba(7,12,26,0.96)',
            border: '1px solid #c9a84c',
            boxShadow: '0 0 12px rgba(201,168,76,0.3)',
            backdropFilter: 'blur(8px)',
            pointerEvents: 'none',
          }}
        >
          Demo Mode
        </div>
      )}

      {/* ── Mobile bottom nav ────────────────────────────────────────── */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 z-[200] flex"
        style={{
          background: 'rgba(7,12,26,0.98)',
          borderTop: '1px solid rgba(201,168,76,0.1)',
          backdropFilter: 'blur(20px)',
          height: 56,
          paddingBottom: 'env(safe-area-inset-bottom)',
          alignItems: 'center',
        }}
      >
        {primaryItems.map(item => (
          <button
            key={item.id}
            onClick={() => handleNav(item.id)}
            className={[
              'flex-1 flex flex-col items-center gap-1 px-1 py-1.5 cursor-pointer',
              'transition-colors duration-150 bg-transparent border-0',
              activeTab === item.id ? 'text-gold' : 'text-muted',
            ].join(' ')}
          >
            <span className="text-lg leading-none">{item.icon}</span>
            <span className="text-[8px] tracking-wide uppercase whitespace-nowrap">{item.label.split(' ')[0]}</span>
          </button>
        ))}

        {/* "More" button opens bottom sheet */}
        <button
          onClick={() => setMoreOpen(true)}
          className={[
            'flex-1 flex flex-col items-center gap-1 px-1 py-1.5 cursor-pointer',
            'transition-colors duration-150 bg-transparent border-0',
            secondaryItems.some(i => i.id === activeTab) ? 'text-gold' : 'text-muted',
          ].join(' ')}
        >
          <span className="text-lg leading-none">⋯</span>
          <span className="text-[8px] tracking-wide uppercase">More</span>
        </button>
      </nav>

      {/* ── Mobile "more" sheet overlay ──────────────────────────────── */}
      {moreOpen && (
        <div
          className="md:hidden fixed inset-0 z-[290]"
          style={{ background: 'rgba(7,12,26,0.7)' }}
          onClick={() => setMoreOpen(false)}
        />
      )}
      <div
        className={[
          'md:hidden fixed bottom-0 left-0 right-0 z-[300] rounded-t-2xl',
          'transition-transform duration-200',
          moreOpen ? 'translate-y-0' : 'translate-y-full',
        ].join(' ')}
        style={{
          background: '#0d1528',
          borderTop: '1px solid rgba(201,168,76,0.2)',
          paddingBottom: 'max(24px, env(safe-area-inset-bottom))',
        }}
      >
        {secondaryItems.map(item => (
          <button
            key={item.id}
            onClick={() => handleNav(item.id)}
            className={[
              'w-full flex items-center gap-3.5 px-6 py-3.5 text-sm',
              'cursor-pointer bg-transparent border-0 text-left',
              activeTab === item.id ? 'text-gold' : 'text-dim',
            ].join(' ')}
          >
            <span className="text-lg w-6 text-center">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </div>

    </div>
  )
}
