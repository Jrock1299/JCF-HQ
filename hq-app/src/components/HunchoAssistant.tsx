import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { AGENT_MAP } from '../data/agentConfig'
import AgentAvatar from './AgentAvatar'

const HUNCHO = AGENT_MAP['huncho']

interface Msg {
  from: 'agent' | 'jase'
  text: string
}

// Page-name lookup so Huncho knows where Jase is standing.
const PAGE: Record<string, string> = {
  '/': 'the command center',
  '/trading': 'the trading floor',
  '/finances': 'the books',
  '/intelligence': 'the intel desk',
  '/hub': 'the agent hub',
  '/agents': 'the roster',
}

// Canned in-character glossary. Local logic only — no LLM wiring yet, but the
// keyword→answer shape drops straight into a real backend later.
const GLOSSARY: { keys: string[]; answer: string }[] = [
  {
    keys: ['compress', 'coiled', 'coil', 'range-bound', 'range bound'],
    answer:
      "Compressed just means the market's coiled up tight, barely movin' — like a spring gettin' pressed down. No clear direction yet. Play is: don't guess which way it snaps, wait for it to actually break, then ride that. — H",
  },
  {
    keys: ['r-multiple', 'r multiple', 'rmultiple', '1r', '2r', ' r ', 'r:r', 'r/r'],
    answer:
      "R-multiple's how we size a trade in units of risk, not dollars. 1R is what you put on the line; make 2R and you doubled your risk in profit. Keeps the whole family honest — we talk in R. — H",
  },
  {
    keys: ['adr'],
    answer:
      "ADR — average daily range. How much an instrument usually travels in a day. Tells you how much room there is to work before you're askin' the tape for too much. — H",
  },
  {
    keys: ['win rate', 'winrate', 'win-rate'],
    answer:
      "Win rate's the percentage that come back green. But listen — high win rate with tiny wins and fat losses still sinks you. Win rate without R sittin' next to it don't mean much. — H",
  },
  {
    keys: ['drawdown', 'draw down', ' dd'],
    answer:
      "Drawdown's how far the account's dropped from its high-water mark. Every operation bleeds sometimes — the game is keepin' the bleed small enough to live to the next run. — H",
  },
  {
    keys: ['profit factor', 'pf ', 'pf.', 'profit-factor', 'profitfactor'],
    answer:
      "Profit factor — gross wins over gross losses. Above 1 you're makin' money, below 1 you're donatin'. Norman wants north of 1.2 before he blesses anything for real size. — H",
  },
  {
    keys: ['sharpe'],
    answer:
      "Sharpe ratio's your return measured against how wild the ride was. High Sharpe, smooth money; low Sharpe, you're white-knucklin' it for the same gain. Under 0.5 and Norman fails you. — H",
  },
]

function answerFor(text: string, page: string): string {
  const q = ` ${text.toLowerCase()} `
  for (const g of GLOSSARY) {
    if (g.keys.some((k) => q.includes(k))) return g.answer
  }
  return `I hear you. You're lookin' at ${page} right now — ask me about a number you see and I'll break it down plain. Regime, R-multiple, drawdown, profit factor, whatever's got you turned around. — H`
}

export default function HunchoAssistant() {
  const loc = useLocation()
  const page = PAGE[loc.pathname] || 'the desk'
  const [open, setOpen] = useState(false)
  const [seeded, setSeeded] = useState(false)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [typing, setTyping] = useState(false)
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  // Seed a page-aware greeting the first time Huncho is opened.
  useEffect(() => {
    if (open && !seeded) {
      setMsgs([
        {
          from: 'agent',
          text: `Aye. You caught me. You're over on ${page} — anything on the screen you want me to explain, just say it. That's what I'm here for. — H`,
        },
      ])
      setSeeded(true)
    }
  }, [open, seeded, page])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [msgs.length, typing])

  function send() {
    const text = input.trim()
    if (!text) return
    setInput('')
    setMsgs((m) => [...m, { from: 'jase', text }])
    window.setTimeout(() => setTyping(true), 500)
    window.setTimeout(() => {
      setTyping(false)
      setMsgs((m) => [...m, { from: 'agent', text: answerFor(text, page) }])
    }, 1800)
  }

  return (
    <>
      {/* Collapsed launcher */}
      <AnimatePresence>
        {!open && (
          <motion.button
            key="huncho-fab"
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            onClick={() => setOpen(true)}
            aria-label="Open Huncho assistant"
            style={{
              position: 'fixed',
              bottom: 24,
              right: 24,
              width: 60,
              height: 60,
              borderRadius: '50%',
              padding: 0,
              zIndex: 60,
              background: 'var(--surface-solid)',
              border: '1.5px solid var(--gold-border)',
              boxShadow: '0 0 0 3px rgba(212,168,67,0.10), 0 8px 28px rgba(0,0,0,0.5), 0 0 22px -4px rgba(212,168,67,0.55)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              overflow: 'hidden',
            }}
          >
            <AgentAvatar agent={HUNCHO} size={54} />
            <span
              style={{
                position: 'absolute',
                top: 3,
                right: 3,
                width: 12,
                height: 12,
                borderRadius: 50,
                background: 'var(--green)',
                border: '2px solid var(--surface-solid)',
                boxShadow: '0 0 6px rgba(34,197,94,0.8)',
              }}
            />
          </motion.button>
        )}
      </AnimatePresence>

      {/* Expanded chat panel */}
      <AnimatePresence>
        {open && (
          <motion.div
            key="huncho-panel"
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="glass"
            style={{
              position: 'fixed',
              bottom: 24,
              right: 24,
              width: 350,
              maxWidth: 'calc(100vw - 32px)',
              height: 480,
              maxHeight: 'calc(100vh - 48px)',
              zIndex: 61,
              display: 'flex',
              flexDirection: 'column',
              padding: 0,
              overflow: 'hidden',
              border: '1px solid var(--gold-border)',
            }}
          >
            {/* Header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 11,
                padding: '13px 14px',
                borderBottom: '0.5px solid var(--glass-border)',
                background: 'linear-gradient(180deg, rgba(212,168,67,0.10), transparent)',
              }}
            >
              <AgentAvatar agent={HUNCHO} size={36} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 600 }}>Huncho 👑</div>
                <div className="mono" style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                  Orchestrator · always on
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                style={{ fontSize: 18, color: 'var(--text-dim)', width: 28, height: 28, borderRadius: 8, lineHeight: 1 }}
              >
                ✕
              </button>
            </div>

            {/* Messages */}
            <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '14px 14px 6px' }}>
              {msgs.map((m, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    justifyContent: m.from === 'jase' ? 'flex-end' : 'flex-start',
                    marginBottom: 10,
                  }}
                >
                  <div
                    className={m.from === 'jase' ? 'glass-gold' : 'glass'}
                    style={{
                      maxWidth: '82%',
                      padding: '9px 12px',
                      borderRadius: m.from === 'jase' ? '14px 4px 14px 14px' : '4px 14px 14px 14px',
                      fontSize: 13,
                      lineHeight: 1.5,
                    }}
                  >
                    {m.text}
                  </div>
                </div>
              ))}
              <AnimatePresence>
                {typing && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span className="mono" style={{ fontSize: 10, color: 'var(--gold)' }}>Huncho</span>
                    <span className="typing-dots"><span /><span /><span /></span>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Input */}
            <div style={{ padding: '10px 12px 12px', borderTop: '0.5px solid var(--glass-border)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') send() }}
                  placeholder="Ask Huncho…"
                  style={{
                    flex: 1,
                    padding: '9px 12px',
                    fontSize: 13,
                    borderRadius: 10,
                    background: 'var(--input-bg)',
                    border: '0.5px solid var(--glass-border)',
                    color: 'var(--text-hi)',
                    outline: 'none',
                  }}
                />
                <button
                  onClick={send}
                  style={{
                    padding: '9px 14px',
                    borderRadius: 10,
                    fontWeight: 600,
                    fontSize: 13,
                    color: '#07080f',
                    background: 'linear-gradient(90deg,#d4a843,#f0c060)',
                  }}
                >
                  Send
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
