import { Routes, Route } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import Layout from './components/Layout'

// Route-level code splitting: each page loads its own JS chunk on navigation.
// recharts (used only by Trading + Finances) is hoisted into a shared async
// chunk and stays out of the initial bundle entirely.
const Home = lazy(() => import('./pages/Home'))
const Trading = lazy(() => import('./pages/Trading'))
const Finances = lazy(() => import('./pages/Finances'))
const Intelligence = lazy(() => import('./pages/Intelligence'))
const AgentHub = lazy(() => import('./pages/AgentHub'))
const Agents = lazy(() => import('./pages/Agents'))

function RouteFallback() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '60vh',
        color: 'var(--text-mute)',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        letterSpacing: '0.05em',
      }}
    >
      loading…
    </div>
  )
}

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/trading" element={<Trading />} />
          <Route path="/finances" element={<Finances />} />
          <Route path="/intelligence" element={<Intelligence />} />
          <Route path="/hub" element={<AgentHub />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="*" element={<Home />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}
