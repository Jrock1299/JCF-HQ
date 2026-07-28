/** TRADING — Ether Ledger direction.
 *
 * Neo-pop treatment: each desk is a big rounded section with tinted stat
 * cards, a chunky segmented win/loss donut (conic, colourful), and pill
 * badges. Sans-forward numerals, 20px radius lock, tinted shadows, no blur.
 */
import type { ReactNode } from 'react'
import EditableValue from '../../components/EditableValue'
import AgentAvatar from '../../components/AgentAvatar'
import { AGENT_MAP } from '../../data/agentConfig'
import { useHQData, fmtUSD } from '../../hooks/useHQData'
import { EtherGreeting, FeedAge } from '../shared'

export default function TradingEther() {
  return (
    <div className="page-pad ether-root">
      <EtherGreeting />
      <BladeSection />
      <div style={{ height: 26 }} />
      <JerrySection />
    </div>
  )
}

function BladeSection() {
  const bal = useHQData('blade-balance').data
  const manual = useHQData('blade-manual').data
  const lensVal = useHQData('lens-validation').data

  const balance = bal?.balance ?? 0
  const pnlToday = manual?.pnl_today ?? 0
  const winRate = Number(manual?.win_rate ?? 0)
  const wins = Number(manual?.wins ?? 0)
  const losses = Number(manual?.losses ?? 0)
  const verdict = lensVal?.agent_reports?.blade?.verdict ?? 'UNKNOWN'

  return (
    <section className="ether-card">
      <DeskHead id="blade" sub={`Lens validates · ${verdict}`} right={<FeedAge iso={lensVal?.date} />} />

      <div className="ether-stat-row">
        <EtherEdit tint="gold" label="Balance" file="blade_balance.json" path="balance" value={balance} display={(v) => fmtUSD(Number(v) || 0)} />
        <EtherEdit
          tint={Number(pnlToday) < 0 ? 'red' : 'green'} label="P&L today"
          file="blade_manual.json" path="pnl_today" value={pnlToday}
          display={(v) => signed(Number(v) || 0)}
        />
        <EtherEdit tint="blue" label="Win rate" file="blade_manual.json" path="win_rate" value={winRate} display={(v) => `${(Number(v) || 0).toFixed(1)}%`} />
        <EtherEdit tint="purple" label="Session" file="blade_manual.json" path="session" value={manual?.session ?? '—'} type="text" />
      </div>

      <div className="ether-split">
        {/* segmented donut */}
        <div className="ether-donut-zone">
          <SegmentDonut wins={wins} losses={losses} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <DonutKey color="#7ce495" label="Wins" file="blade_manual.json" path="wins" value={wins} />
            <DonutKey color="#ff6b6b" label="Losses" file="blade_manual.json" path="losses" value={losses} />
            <div className="soft" style={{ fontSize: 12, color: 'var(--text-mute)', maxWidth: 170, lineHeight: 1.5 }}>
              Fresh book — the wheel colours in as clusters close.
            </div>
          </div>
        </div>

        {/* rails as pills */}
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Risk rails</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <RailPill>≤1% / trade</RailPill>
            <RailPill>≤2% / cluster</RailPill>
            <RailPill>−4% daily halt</RailPill>
            <RailPill>$100 floor</RailPill>
            <RailPill>fill-relative SL/TP</RailPill>
          </div>
          <div className="soft" style={{ fontSize: 12.5, color: 'var(--text-dim)', marginTop: 14, lineHeight: 1.55 }}>
            The live-paper executor fires every 15 minutes inside the London and NY
            killzones on SPX500, DE30 and XAU — the three instruments with a
            validated strategy in the library. Rails are enforced in code, not policy.
          </div>
        </div>
      </div>
    </section>
  )
}

function JerrySection() {
  const jerry = useHQData('jerry-portfolio').data
  const vicVal = useHQData('victoria-validation').data
  const j = vicVal?.agent_reports?.jerry

  return (
    <section className="ether-card">
      <DeskHead id="jerry" sub={`Victoria validates · ${j?.verdict ?? 'UNKNOWN'}`} right={<FeedAge iso={vicVal?.date} />} />
      <div className="ether-stat-row">
        <Tint label="Portfolio" tint="blue" value={fmtUSD(jerry?.balance ?? null)} />
        <Tint label="Total P&L" tint={(jerry?.total_pnl ?? 0) < 0 ? 'red' : 'green'} value={signed(jerry?.total_pnl ?? 0)} />
        <Tint label="Graded trades" tint="purple" value={`${j?.total_trades ?? '--'}`} />
        <Tint label="Status" tint="gold" value="Idling" sub="library gate holds every buy" />
      </div>
      <div className="ether-regime-note" style={{ marginTop: 4 }}>
        Equity strategy graded <strong>{j?.verdict ?? '—'}</strong> — Jerry stays online
        but trades nothing until Lens or Victoria promote a validated strategy for his book.
      </div>
    </section>
  )
}

// ── pieces ────────────────────────────────────────────────────────────

function DeskHead({ id, sub, right }: { id: string; sub: string; right?: ReactNode }) {
  const a = AGENT_MAP[id]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 13, marginBottom: 18 }}>
      <AgentAvatar agent={a} size={44} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 21, fontWeight: 700, letterSpacing: '-0.01em' }}>{a.name} {a.emoji}</div>
        <div className="soft" style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 1 }}>{sub}</div>
      </div>
      {right}
    </div>
  )
}

function EtherEdit({
  tint, label, file, path, value, display, type = 'number',
}: {
  tint: 'green' | 'red' | 'gold' | 'blue' | 'purple'
  label: string; file: string; path: string; value: number | string | null
  display?: (v: any) => ReactNode; type?: 'number' | 'text'
}) {
  return (
    <div className={`ether-tint ether-tint-${tint}`}>
      <div style={{ fontSize: 12.5, fontWeight: 500, opacity: 0.75 }}>{label}</div>
      <EditableValue
        file={file} path={path} value={value} type={type} display={display}
        style={{ fontSize: 23, fontWeight: 700, letterSpacing: '-0.015em' }}
      />
    </div>
  )
}

function Tint({ tint, label, value, sub }: {
  tint: 'green' | 'red' | 'gold' | 'blue' | 'purple'
  label: string; value: ReactNode; sub?: string
}) {
  return (
    <div className={`ether-tint ether-tint-${tint}`}>
      <div style={{ fontSize: 12.5, fontWeight: 500, opacity: 0.75 }}>{label}</div>
      <div style={{ fontSize: 23, fontWeight: 700, letterSpacing: '-0.015em', marginTop: 2 }}>{value}</div>
      {sub && <div className="soft" style={{ fontSize: 11, opacity: 0.65, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

/** Chunky two-segment conic donut, ethereal-style: mint for wins, coral for
 *  losses, soft rounded hole with the big number. */
function SegmentDonut({ wins, losses }: { wins: number; losses: number }) {
  const total = wins + losses
  const winDeg = total > 0 ? (wins / total) * 360 : 0
  return (
    <div
      className="ether-donut"
      style={{
        background: total > 0
          ? `conic-gradient(#7ce495 0deg ${winDeg}deg, #ff6b6b ${winDeg}deg 360deg)`
          : 'conic-gradient(rgba(128,128,140,0.18) 0deg 360deg)',
      }}
    >
      <div className="ether-donut-hole">
        <span style={{ fontSize: 26, fontWeight: 700 }}>{total > 0 ? `${((wins / total) * 100).toFixed(0)}%` : '—'}</span>
        <span className="soft" style={{ fontSize: 10.5, color: 'var(--text-mute)' }}>win rate</span>
      </div>
    </div>
  )
}

function DonutKey({ color, label, file, path, value }: {
  color: string; label: string; file: string; path: string; value: number
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
      <span style={{ width: 10, height: 10, borderRadius: 99, background: color }} />
      <span className="soft" style={{ fontSize: 12.5, width: 52 }}>{label}</span>
      <EditableValue file={file} path={path} value={value} type="number" style={{ fontSize: 17, fontWeight: 700 }} />
    </div>
  )
}

function RailPill({ children }: { children: ReactNode }) {
  return <span className="ether-rail-pill">{children}</span>
}

function signed(n: number) { return `${n >= 0 ? '+' : '−'}$${Math.abs(n).toFixed(2)}` }
