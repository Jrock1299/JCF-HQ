import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import AgentAvatar from '../components/AgentAvatar'
import ChatBubble from '../components/ChatBubble'
import AgentDot from '../components/AgentDot'
import { AGENTS, AGENT_MAP } from '../data/agentConfig'
import { THREAD_MAP, type HubMessage } from '../data/seedMessages'

// Ordered conversation list (BUILDING agents drop to the bottom).
const ORDER = [...AGENTS].sort((a, b) => {
  const rank = (s: string) => (s === 'LIVE' ? 0 : s === 'STANDBY' ? 1 : 2)
  return rank(a.state) - rank(b.state)
})

function nowClock() {
  return new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
}

export default function AgentHub() {
  const [params] = useSearchParams()
  const initial = params.get('agent')
  const firstId = initial && AGENT_MAP[initial] ? initial : ORDER[0].id

  const [activeId, setActiveId] = useState(firstId)
  const [query, setQuery] = useState('')
  // per-agent local message state (seed + anything sent this session)
  const [threads, setThreads] = useState<Record<string, HubMessage[]>>(() =>
    Object.fromEntries(AGENTS.map((a) => [a.id, [...(THREAD_MAP[a.id]?.messages || [])]])),
  )
  const [typing, setTyping] = useState<Record<string, boolean>>({})
  const [replyIdx, setReplyIdx] = useState<Record<string, number>>({})
  const [input, setInput] = useState('')

  useEffect(() => {
    if (initial && AGENT_MAP[initial]) setActiveId(initial)
  }, [initial])

  const active = AGENT_MAP[activeId]
  const messages = threads[activeId] || []
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, typing[activeId]])

  const list = useMemo(
    () => ORDER.filter((a) => a.name.toLowerCase().includes(query.toLowerCase()) || a.role.toLowerCase().includes(query.toLowerCase())),
    [query],
  )

  function send() {
    const text = input.trim()
    if (!text) return
    const id = activeId
    setInput('')
    setThreads((prev) => ({ ...prev, [id]: [...prev[id], { from: 'jase', text, time: nowClock() }] }))

    // typing → reply flow
    window.setTimeout(() => setTyping((p) => ({ ...p, [id]: true })), 1000)
    window.setTimeout(() => {
      const pool = THREAD_MAP[id]?.replies || ['On it.']
      const idx = (replyIdx[id] || 0) % pool.length
      setReplyIdx((p) => ({ ...p, [id]: idx + 1 }))
      setTyping((p) => ({ ...p, [id]: false }))
      setThreads((prev) => ({ ...prev, [id]: [...prev[id], { from: 'agent', text: pool[idx], time: nowClock() }] }))
    }, 2500)
  }

  return (
    <div style={{ height: '100vh', display: 'flex', overflow: 'hidden' }}>
      {/* Left panel */}
      <div
        style={{
          width: 300,
          flexShrink: 0,
          borderRight: '0.5px solid var(--glass-border)',
          background: 'var(--panel-bg)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ padding: '20px 18px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <img className="logo-img" src="/logo-jcf.png" alt="JCF" style={{ width: 26, height: 26 }} />
          <span style={{ fontWeight: 600, fontSize: 16 }}>Agent Hub</span>
        </div>
        <div style={{ padding: '0 14px 12px' }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search agents…"
            className="mono"
            style={{
              width: '100%', padding: '8px 12px', fontSize: 12, borderRadius: 9,
              background: 'var(--input-bg)', border: '0.5px solid var(--glass-border)',
              color: 'var(--text-hi)', outline: 'none',
            }}
          />
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {list.map((a) => {
            const msgs = threads[a.id] || []
            const last = msgs[msgs.length - 1]
            const unread = THREAD_MAP[a.id]?.unread && a.id !== activeId
            const isActive = a.id === activeId
            return (
              <button
                key={a.id}
                onClick={() => setActiveId(a.id)}
                style={{
                  width: '100%', display: 'flex', gap: 11, alignItems: 'center', textAlign: 'left',
                  padding: '10px 10px', borderRadius: 10, marginBottom: 2,
                  background: isActive ? 'rgba(212,168,67,0.10)' : 'transparent',
                  border: isActive ? '0.5px solid var(--gold-border)' : '0.5px solid transparent',
                  transition: 'background 0.15s',
                }}
              >
                <div style={{ position: 'relative' }}>
                  <AgentAvatar agent={a} size={36} />
                  <span style={{ position: 'absolute', bottom: 0, right: 0 }}><AgentDot state={a.state} /></span>
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 13.5, fontWeight: isActive ? 600 : 500 }}>{a.name} {a.emoji}</span>
                    <span className="mono-meta" style={{ flexShrink: 0 }}>{last?.time || ''}</span>
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--text-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 1 }}>
                    {last ? truncate(last.text, 34) : a.role}
                  </div>
                </div>
                {unread && <span style={{ width: 8, height: 8, borderRadius: 50, background: 'var(--gold)', flexShrink: 0 }} />}
              </button>
            )
          })}
        </div>

        <div style={{ padding: 12, borderTop: '0.5px solid var(--glass-border)' }}>
          <button className="badge badge-purple" style={{ width: '100%', justifyContent: 'center', padding: '9px' }}>
            📢 Broadcast to all
          </button>
        </div>
      </div>

      {/* Right panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ padding: '16px 96px 16px 24px', borderBottom: '0.5px solid var(--glass-border)', display: 'flex', alignItems: 'center', gap: 13, background: 'var(--panel-bg)' }}>
          <AgentAvatar agent={active} size={40} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{active.name} {active.emoji}</div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>{active.role} · {active.model}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <AgentDot state={active.state} />
            <span className="mono" style={{ fontSize: 10, color: active.state === 'LIVE' ? 'var(--green)' : active.state === 'STANDBY' ? 'var(--amber)' : 'var(--purple)' }}>{active.state}</span>
          </div>
        </div>

        {/* Messages */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '24px 24px 8px' }}>
          {messages.map((m, i) => (
            <ChatBubble key={i} from={m.from} text={m.text} time={m.time} agent={active} />
          ))}
          <AnimatePresence>
            {typing[activeId] && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} style={{ display: 'flex', gap: 10, alignItems: 'center', marginLeft: 40 }}>
                <span className="mono" style={{ fontSize: 11, color: 'var(--gold)' }}>{active.name} is typing</span>
                <span className="typing-dots"><span /><span /><span /></span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Input */}
        <div style={{ padding: '14px 24px 20px', borderTop: '0.5px solid var(--glass-border)' }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') send() }}
              placeholder={`Message ${active.name}…`}
              style={{
                flex: 1, padding: '12px 16px', fontSize: 14, borderRadius: 12,
                background: 'var(--input-bg)', border: '0.5px solid var(--glass-border)',
                color: 'var(--text-hi)', outline: 'none',
              }}
            />
            <button
              onClick={send}
              style={{
                padding: '12px 20px', borderRadius: 12, fontWeight: 600, fontSize: 14, color: '#07080f',
                background: 'linear-gradient(90deg,#d4a843,#f0c060)',
              }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n).trimEnd() + '…' : s
}
