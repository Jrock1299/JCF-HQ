import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Trading from './pages/Trading'
import Finances from './pages/Finances'
import Intelligence from './pages/Intelligence'
import AgentHub from './pages/AgentHub'
import Agents from './pages/Agents'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/trading" element={<Trading />} />
        <Route path="/finances" element={<Finances />} />
        <Route path="/intelligence" element={<Intelligence />} />
        <Route path="/hub" element={<AgentHub />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="*" element={<Home />} />
      </Routes>
    </Layout>
  )
}
