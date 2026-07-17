import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import AgentAvatar from '../components/AgentAvatar'
import ChatBubble from '../components/ChatBubble'
import AgentDot from '../components/AgentDot'
import { AGENTS, AGENT_MAP } from '../data/agentConfig'
import { THREAD_MAP, GROUP_SEED, type HubMessage } from '../data/seedMessages'

const GROUP_ID = 'group'
const GROUP_MEMBERS = ['huncho', 'lens', 'blade', 'jerry', 'norman', 'victoria']

// Ordered conversation list (BUILDING agents drop to the bottom).
const ORDER = [...AGENTS].sort((a, b) => {
  const rank = (s: string) => (s === 'LIVE' ? 0 : s === 'STANDBY' ? 1 : 2)
  return rank(a.state) - rank(b.state)
})

// Keyword → agent routing for group-chat replies.
const ROUTES: { keys: string[]; id: string }[] = [
  { keys: ['blade', 'orb', 'forex', 'indices', 'spx', 'dax', 'breakout'], id: 'blade' },
  { keys: ['jerry', 'stock', 'alpaca', 'option', 'equit', 'watchlist'], id: 'jerry' },
  { keys: ['risk', 'drawdown', 'norman', 'monte', 'sharpe', 'ruin', 'size'], id: 'norman' },
  { keys: ['macro', 'lens', 'news', 'cpi', 'fed', 'dollar', 'gold', 'oil'], id: 'lens' },
  { keys: ['money', 'cost', 'pnl', 'p&l', 'ledger', 'victoria', 'budget', 'cash'], id: 'victoria' },
  { keys: ['regime', 'jarvis', 'trend', 'compress', 'range'], id: 'jarvis' },
  { keys: ['tao', 'stake', 'bittensor', 'subnet'], id: 'tao' },
  { keys: ['edge', 'sma', 'crossover'], id: 'edge' },
  { keys: ['tool', 'skill', 'mcp', 'lucy', 'meme', 'solana'], id: 'lucy' },
]

const AGENT_REACT: Record<string, string> = {
  victoria: '🔥', norman: '✅', lucy: '👀', jerry: '✅', blade: '✅',
  huncho: '🔥', lens: '👀', jarvis: '👍', tao: '👍', edge: '✅',
}

function nowClock() {
  return new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
}
function liveOther(exclude: string): string {
  const pool = AGENTS.filter((a) => a.state === 'LIVE' && a.id !== exclude)
  return pool[Math.floor(Math.random() * pool.length)]?.id || 'lens'
}
function groupResponders(text: string): string[] {
  const q = text.toLowerCase()
  let ids = Array.from(new Set(ROUTES.filter((r) => r.keys.some((k) => q.includes(k))).map((r) => r.id)))
  if (ids.length === 0) ids = ['huncho', liveOther('huncho')]
  else if (ids.length === 1) ids = [ids[0], 'huncho']
  return Array.from(new Set(ids)).slice(0, 3)
}

export default function AgentHub() {
  const [params] = useSearchParams()
  const initial = params.get('agent')
  const firstId = initial && AGENT_MAP[initial] ? initial : GROUP_ID

  const [activeId, setActiveId] = useState(firstId)
  const [query, setQuery] = useState('')
  const [threads, setThreads] = useState<Record<string, HubMessage[]>>(() => ({
    [GROUP_ID]: [...GROUP_SEED],
    ...Object.fromEntries(AGENTS.map((a) => [a.id, [...(THREAD_MAP[a.id]?.messages || [])]])),
  }))
  const [typing, setTyping] = useState<Record<string, string | null>>({})
  const [replyIdx, setReplyIdx] = useState<Record<string, number>>({})
  const [input, setInput] = useState('')
  const [picker, setPicker] = useState<{ tid: string; idx: number } | null>(null)

  useEffect(() => {
    if (initial && AGENT_MAP[initial]) setActiveId(initial)
  }, [initial])

  const isGroup = activeId === GROUP_ID
  const active = isGroup ? null : AGENT_MAP[activeId]
  const messages = threads[activeId] || []
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, typing[activeId]])

  const list = useMemo(
    () => ORDER.filter((a) => a.name.toLowerCase().includes(query.toLowerCase()) || a.role.toLowerCase().includes(query.toLowerCase())),
    [query],
  )

  function addReaction(tid: string, idx: number, emoji: string) {
    setThreads((prev) => {
      const arr = [...(prev[tid] || [])]
      if (!arr[idx]) return prev
      const existing = arr[idx].reactions || []
      arr[idx] = { ...arr[idx], reactions: existing.includes(emoji) ? existing : [...existing, emoji] }
      return { ...prev, [tid]: arr }
    })
  }

  function send() {
    const text = input.trim()
    if (!text) return
    const tid = activeId
    setInput('')
    let jaseIdx = 0
    setThreads((prev) => {
      const arr = [...(prev[tid] || [])]
      jaseIdx = arr.length
      arr.push({ from: 'jase', text, time: nowClock() })
      return { ...prev, [tid]: arr }
    })

    if (isGroup) {
      const responders = groupResponders(text)
      responders.forEach((id, i) => {
        const base = 900 + i * 1900
        window.setTimeout(() => setTyping((p) => ({ ...p, [tid]: AGENT_MAP[id]?.name || '…' })), base)
        window.setTimeout(() => {
          const pool = THREAD_MAP[id]?.replies || ['On it.']
          const idx = (replyIdx[id] || 0) % pool.length
          setReplyIdx((p) => ({ ...p, [id]: idx + 1 }))
          setTyping((p) => ({ ...p, [tid]: null }))
          setThreads((prev) => ({ ...prev, [tid]: [...(prev[tid] || []), { from: 'agent', agentId: id, text: pool[idx], time: nowClock() }] }))
          // occasional in-character reaction to Jase's message
          if (i === 0 && Math.random() < 0.55) addReaction(tid, jaseIdx, AGENT_REACT[id] || '👍')
        }, base + 1400)
      })
      return
    }

    // 1:1 typing → reply
    window.setTimeout(() => setTyping((p) => ({ ...p, [tid]: AGENT_MAP[tid]?.name || '…' })), 1000)
    window.setTimeout(() => {
      const pool = THREAD_MAP[tid]?.replies || ['On it.']
      const idx = (replyIdx[tid] || 0) % pool.length
      setReplyIdx((p) => ({ ...p, [tid]: idx + 1 }))
      setTyping((p) => ({ ...p, [tid]: null }))
      setThreads((prev) => ({ ...prev, [tid]: [...(prev[tid] || []), { from: 'agent', text: pool[idx], time: nowClock() }] }))
      if (Math.random() < 0.45) addReaction(tid, jaseIdx, AGENT_REACT[tid] || '👍')
    }, 2500)
  }

  const headerName = isGroup ? 'Group Chat' : active!.name
  const typingLabel = typing[activeId]

  return (
    <div style={{ height: '100vh', display: 'flex', overflow: 'hidden' }}>
      {/* Left panel */}
      <div
        style={{
          width: 300, flexShrink: 0, borderRight: '0.5px solid var(--glass-border)',
          background: 'var(--panel-bg)', backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)',
          display: 'flex', flexDirection: 'column',
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
            style={{ width: '100%', padding: '8px 12px', fontSize: 12, borderRadius: 9, background: 'var(--input-bg)', border: '0.5px solid var(--glass-border)', color: 'var(--text-hi)', outline: 'none' }}
          />
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px' }}>
          {/* Pinned Group Chat */}
          {!query && (
            <button
              onClick={() => setActiveId(GROUP_ID)}
              style={{
                width: '100%', display: 'flex', gap: 11, alignItems: 'center', textAlign: 'left',
                padding: '10px 10px', borderRadius: 10, marginBottom: 6,
                background: isGroup ? 'rgba(212,168,67,0.12)' : 'rgba(212,168,67,0.05)',
                border: isGroup ? '0.5px solid var(--gold-border)' : '0.5px solid var(--gold-border)',
              }}
            >
              <div style={{ position: 'relative', width: 40, height: 36, flexShrink: 0 }}>
                {GROUP_MEMBERS.slice(0, 3).map((id, i) => (
                  <span key={id} style={{ position: 'absolute', left: i * 12, top: i % 2 ? 6 : 0, border: '1.5px solid var(--surface-solid)', borderRadius: 50 }}>
                    <AgentAvatar agent={AGENT_MAP[id]} size={22} />
                  </span>
                ))}
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 13.5, fontWeight: 600 }}>📌 Group Chat</span>
                  <span className="mono-meta">{(threads[GROUP_ID] || []).slice(-1)[0]?.time || ''}</span>
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--text-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 1 }}>
                  The whole family · {GROUP_MEMBERS.length} agents
                </div>
              </div>
            </button>
          )}

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
          <button className="badge badge-purple" onClick={() => setActiveId(GROUP_ID)} style={{ width: '100%', justifyContent: 'center', padding: '9px' }}>
            📢 Broadcast to all
          </button>
        </div>
      </div>

      {/* Right panel */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div style={{ padding: '16px 96px 16px 24px', borderBottom: '0.5px solid var(--glass-border)', display: 'flex', alignItems: 'center', gap: 13, background: 'var(--panel-bg)' }}>
          {isGroup ? (
            <div style={{ position: 'relative', width: 54, height: 40, flexShrink: 0 }}>
              {GROUP_MEMBERS.slice(0, 4).map((id, i) => (
                <span key={id} style={{ position: 'absolute', left: i * 13, top: i % 2 ? 6 : 0, border: '1.5px solid var(--surface-solid)', borderRadius: 50 }}>
                  <AgentAvatar agent={AGENT_MAP[id]} size={24} />
                </span>
              ))}
            </div>
          ) : (
            <AgentAvatar agent={active!} size={40} />
          )}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{isGroup ? '📌 Group Chat' : `${active!.name} ${active!.emoji}`}</div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              {isGroup ? `${GROUP_MEMBERS.map((id) => AGENT_MAP[id].name).join(' · ')}` : `${active!.role} · ${active!.model}`}
            </div>
          </div>
          {!isGroup && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <AgentDot state={active!.state} />
              <span className="mono" style={{ fontSize: 10, color: active!.state === 'LIVE' ? 'var(--green)' : active!.state === 'STANDBY' ? 'var(--amber)' : 'var(--purple)' }}>{active!.state}</span>
            </div>
          )}
        </div>

        {/* Messages */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '24px 24px 8px', position: 'relative' }}>
          {messages.map((m, i) => {
            const msgAgent = m.from === 'agent' ? (m.agentId ? AGENT_MAP[m.agentId] : active || undefined) : undefined
            return (
              <ChatBubble
                key={i}
                from={m.from}
                text={m.text}
                time={m.time}
                agent={msgAgent}
                showName={isGroup || m.from === 'agent'}
                reactions={m.reactions}
                showPicker={picker?.tid === activeId && picker?.idx === i}
                onOpenPicker={() => setPicker({ tid: activeId, idx: i })}
                onPick={(e) => { addReaction(activeId, i, e); setPicker(null) }}
              />
            )
          })}
          <AnimatePresence>
            {typingLabel && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} style={{ display: 'flex', gap: 10, alignItems: 'center', marginLeft: 40 }}>
                <span className="mono" style={{ fontSize: 11, color: 'var(--gold)' }}>{typingLabel} is typing</span>
                <span className="typing-dots"><span /><span /><span /></span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* click-away to close reaction picker */}
        {picker && <div onClick={() => setPicker(null)} style={{ position: 'fixed', inset: 0, zIndex: 2 }} />}

        {/* Input */}
        <div style={{ padding: '14px 24px 20px', borderTop: '0.5px solid var(--glass-border)' }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') send() }}
              placeholder={isGroup ? 'Message the whole family…' : `Message ${headerName}…`}
              style={{ flex: 1, padding: '12px 16px', fontSize: 14, borderRadius: 12, background: 'var(--input-bg)', border: '0.5px solid var(--glass-border)', color: 'var(--text-hi)', outline: 'none' }}
            />
            <button
              onClick={send}
              style={{ padding: '12px 20px', borderRadius: 12, fontWeight: 600, fontSize: 14, color: '#07080f', background: 'linear-gradient(90deg,#d4a843,#f0c060)' }}
            >
              Send
            </button>
          </div>
          <div className="mono-meta" style={{ marginTop: 8, textAlign: 'center' }}>Double-click any message to react</div>
        </div>
      </div>
    </div>
  )
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n).trimEnd() + '…' : s
}
