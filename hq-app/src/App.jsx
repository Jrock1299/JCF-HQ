import { useState, lazy, Suspense } from 'react'
import Layout from './components/Layout.jsx'
import { DemoProvider } from './context/DemoContext.jsx'

// ── Lazy-load every tab (loads once on first visit, then stays mounted) ─
const Dashboard     = lazy(() => import('./components/Dashboard.jsx'))
const Portfolio     = lazy(() => import('./components/Portfolio.jsx'))
const Trading       = lazy(() => import('./components/Trading.jsx'))
const Investing     = lazy(() => import('./components/Investing.jsx'))
const Agents        = lazy(() => import('./components/Agents.jsx'))
const Projects      = lazy(() => import('./components/Projects.jsx'))
const Intelligence  = lazy(() => import('./components/Intelligence.jsx'))
const Basketball    = lazy(() => import('./components/Basketball.jsx'))
const Timeline      = lazy(() => import('./components/Timeline.jsx'))

// ── Tab registry (id must match Layout nav) ────────────────────────────
export const TABS = [
  { id: 'dashboard',     label: 'Dashboard',      icon: '⌂',  component: Dashboard     },
  { id: 'portfolio',     label: 'Portfolio',       icon: '◈',  component: Portfolio     },
  { id: 'intelligence',  label: 'Intelligence',    icon: '◎',  component: Intelligence  },
  { id: 'trading',       label: 'Trading',         icon: '↗',  component: Trading       },
  { id: 'agents',        label: 'Agents',          icon: '◆',  component: Agents        },
  { id: 'projects',      label: 'Projects',        icon: '▣',  component: Projects      },
  { id: 'investing',     label: 'Investing',       icon: '◇',  component: Investing     },
  { id: 'timeline',      label: 'Timeline',        icon: '≡',  component: Timeline      },
  { id: 'basketball',    label: 'Basketball',      icon: '◐',  component: Basketball    },
]

// ── Demo-mode detection ────────────────────────────────────────────────
const params = new URLSearchParams(window.location.search)
export const DEMO_MODE = params.get('demo') === 'true'

function TabFallback() {
  return (
    <div className="flex items-center justify-center h-48 text-muted text-xs tracking-widest uppercase animate-pulse-slow">
      Loading…
    </div>
  )
}

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  // Track which tabs have ever been visited — once loaded, never unmount
  const [mountedTabs, setMountedTabs] = useState(() => new Set(['dashboard']))

  function handleTabChange(id) {
    setActiveTab(id)
    setMountedTabs(prev => {
      if (prev.has(id)) return prev
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }

  return (
    <DemoProvider demo={DEMO_MODE}>
      <Layout activeTab={activeTab} onTabChange={handleTabChange} demoMode={DEMO_MODE}>
        <Suspense fallback={<TabFallback />}>
          {TABS.map(({ id, component: Tab }) => {
            if (!mountedTabs.has(id)) return null
            return (
              <div key={id} style={{ display: activeTab === id ? 'block' : 'none' }}>
                <Tab demoMode={DEMO_MODE} isActive={activeTab === id} />
              </div>
            )
          })}
        </Suspense>
      </Layout>
    </DemoProvider>
  )
}
