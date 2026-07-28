/** TRADING — Command Grid direction.
 *
 * Instrument-panel treatment: a per-desk KPI rail (mono numerals, editable),
 * a glow win/loss arc, the risk rails as a flat spec table with LED markers,
 * and the live-executor state strip. Flat panels, hairline dividers, no
 * nested cards — VISUAL_DENSITY 7 discipline.
 */
import type { ReactNode } from 'react'
import EditableValue from '../../components/EditableValue'
import AgentAvatar from '../../components/AgentAvatar'
import { AGENT_MAP } from '../../data/agentConfig'
import { useHQData, fmtUSD } from '../../hooks/useHQData'
import { CommandStatusBar, FeedAge } from '../shared'

export default function TradingCommand() {
  return (
    <div className="page-pad cmd-root">
      <CommandStatusBar />
      <BladeDesk />
      <div style={{ height: 28 }} />
      <JerryDesk />
    </div>
  )
}

// ── BLADE desk ────────────────────────────────────────────────────────

function BladeDesk() {
  const bal = useHQData('blade-balance').data
  const manual = useHQData('blade-manual').data
  const lensVal = useHQData('lens-validation').data

  const balance = bal?.balance ?? 0
  const pnlToday = manual?.pnl_today ?? 0
  const winRate = Number(manual?.win_rate ?? 0)
  const wins = manual?.wins ?? 0
  const losses = manual?.losses ?? 0
  const session = manual?.session ?? '—'
  const bladeVerdict = lensVal?.agent_reports?.blade?.verdict ?? 'UNKNOWN'

  return (
    <section>
      <DeskHead id="blade" line={`validator: lens · verdict ${bladeVerdict}`} />

      <div className="cmd-rail" style={{ marginBottom: 18 }}>
        <RailEdit label="BALANCE" file="blade_balance.json" path="balance" value={balance} display={(v) => fmtUSD(Number(v) || 0)} tone="accent" />
        <RailEdit
          label="P&L TODAY" file="blade_manual.json" path="pnl_today" value={pnlToday}
          display={(v) => signed(Number(v) || 0)}
          tone={Number(pnlToday) < 0 ? 'red' : 'green'}
        />
        <RailEdit label="WIN RATE" file="blade_manual.json" path="win_rate" value={winRate} display={(v) => `${(Number(v) || 0).toFixed(1)}%`} tone="accent" />
        <RailEdit label="SESSION" file="blade_manual.json" path="session" value={session} type="text" tone="purple" />
      </div>

      <div className="cmd-grid">
        {/* win/loss arc */}
        <div className="cmd-panel" style={{ gridColumn: 'span 5', display: 'flex', gap: 26, alignItems: 'center' }}>
          <GlowArc pct={winRate} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <ArcStat color="var(--green)" label="WINS" file="blade_manual.json" path="wins" value={wins} />
            <ArcStat color="var(--red)" label="LOSSES" file="blade_manual.json" path="losses" value={losses} />
            <span className="mono" style={{ fontSize: 10, color: 'var(--text-mute)', maxWidth: 160, lineHeight: 1.5 }}>
              Ring fills as clusters close and the validator grades the edge.
            </span>
          </div>
        </div>

        {/* rails spec table */}
        <div className="cmd-panel" style={{ gridColumn: 'span 7' }}>
          <div className="mono" style={{ fontSize: 9.5, letterSpacing: '0.16em', color: 'var(--text-mute)', marginBottom: 12 }}>RISK RAILS — HARD, NOT ADVISORY</div>
          <table className="cmd-spec">
            <tbody>
              <SpecRow k="Risk per trade" v="≤ 1%" note="library RISK_PCT 0.75%" ok />
              <SpecRow k="Risk per cluster" v="≤ 2%" note="D3 weights 20/30/50" ok />
              <SpecRow k="Daily drawdown halt" v="−4%" note="/tmp state, resets per UTC day" ok />
              <SpecRow k="Balance floor" v="$100" note="refuse to trade below" ok />
              <SpecRow k="SL / TP placement" v="fill-relative" note="stopLossOnFill.distance + TradeCRCDO" ok />
            </tbody>
          </table>
          <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="cmd-led cmd-led-green" />
            <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-dim)' }}>
              live-paper executor · */15 in London + NY killzones · SPX500 / DE30 / XAU
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}

// ── JERRY desk ────────────────────────────────────────────────────────

function JerryDesk() {
  const jerry = useHQData('jerry-portfolio').data
  const vicVal = useHQData('victoria-validation').data
  const j = vicVal?.agent_reports?.jerry

  return (
    <section>
      <DeskHead id="jerry" line={`validator: victoria · verdict ${j?.verdict ?? 'UNKNOWN'}`} />
      <div className="cmd-rail">
        <RailPlain label="PORTFOLIO" value={fmtUSD(jerry?.balance ?? null)} tone="accent" />
        <RailPlain
          label="TOTAL P&L" value={signed(jerry?.total_pnl ?? 0)}
          tone={(jerry?.total_pnl ?? 0) < 0 ? 'red' : 'green'}
        />
        <RailPlain label="GRADED TRADES" value={`${j?.total_trades ?? '--'}`} tone="accent" />
        <RailPlain label="GATE" value="LIBRARY" tone="amber"
          sub="0 deployable → all buys refused" />
      </div>
      <div className="cmd-panel" style={{ marginTop: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span className="cmd-led cmd-led-amber" />
          <span className="mono" style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            Equity strategy graded {j?.verdict ?? '—'} ({j?.total_trades ?? 0} trades, WR {j?.win_rate ?? '--'}%) — held from live-paper until a validated strategy lands in the library.
          </span>
          <FeedAge iso={vicVal?.date} label="victoria-validation" />
        </div>
      </div>
    </section>
  )
}

// ── pieces ────────────────────────────────────────────────────────────

function DeskHead({ id, line }: { id: string; line: string }) {
  const a = AGENT_MAP[id]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '18px 0 14px' }}>
      <AgentAvatar agent={a} size={38} />
      <div>
        <span className="mono" style={{ fontSize: 16, fontWeight: 600, letterSpacing: '0.04em' }}>{a.name.toUpperCase()}</span>
        <div className="mono" style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 1, letterSpacing: '0.06em' }}>{line}</div>
      </div>
    </div>
  )
}

function RailEdit({
  label, file, path, value, display, type = 'number', tone,
}: {
  label: string; file: string; path: string; value: number | string | null
  display?: (v: any) => ReactNode; type?: 'number' | 'text'
  tone?: 'accent' | 'green' | 'red' | 'purple' | 'amber'
}) {
  return (
    <div className="cmd-rail-cell">
      <div className="mono" style={{ fontSize: 9, letterSpacing: '0.16em', color: 'var(--text-mute)' }}>{label}</div>
      <EditableValue
        file={file} path={path} value={value} type={type} display={display}
        className="mono cmd-rail-num" style={{ color: toneColor(tone) }}
      />
    </div>
  )
}

function RailPlain({ label, value, sub, tone }: {
  label: string; value: ReactNode; sub?: string
  tone?: 'accent' | 'green' | 'red' | 'purple' | 'amber'
}) {
  return (
    <div className="cmd-rail-cell">
      <div className="mono" style={{ fontSize: 9, letterSpacing: '0.16em', color: 'var(--text-mute)' }}>{label}</div>
      <div className="mono cmd-rail-num" style={{ color: toneColor(tone) }}>{value}</div>
      {sub && <div className="mono" style={{ fontSize: 9.5, color: 'var(--text-dim)', marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

function toneColor(t?: string) {
  return t === 'green' ? 'var(--green)' : t === 'red' ? 'var(--red)'
    : t === 'purple' ? 'var(--purple)' : t === 'amber' ? 'var(--amber)' : 'var(--dir-accent)'
}

/** Conic-gradient arc with glow — the cost-card donut treatment applied to
 *  win rate. Pure CSS conic; no chart lib needed for a single arc. */
function GlowArc({ pct }: { pct: number }) {
  const deg = Math.max(0, Math.min(100, pct)) * 3.6
  return (
    <div className="cmd-arc" style={{ ['--arc-deg' as any]: `${deg}deg` }}>
      <div className="cmd-arc-hole">
        <span className="mono" style={{ fontSize: 22, fontWeight: 600, color: 'var(--dir-accent)' }}>{pct.toFixed(0)}%</span>
        <span className="mono" style={{ fontSize: 8.5, letterSpacing: '0.14em', color: 'var(--text-mute)' }}>WIN RATE</span>
      </div>
    </div>
  )
}

function ArcStat({ color, label, file, path, value }: {
  color: string; label: string; file: string; path: string; value: number
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, background: color, boxShadow: `0 0 8px ${color}` }} />
      <span className="mono" style={{ fontSize: 9.5, letterSpacing: '0.12em', color: 'var(--text-mute)', width: 52 }}>{label}</span>
      <EditableValue file={file} path={path} value={value} type="number" className="mono" style={{ fontSize: 16, fontWeight: 600 }} />
    </div>
  )
}

function SpecRow({ k, v, note, ok }: { k: string; v: string; note: string; ok?: boolean }) {
  return (
    <tr>
      <td style={{ width: 14 }}><span className={`cmd-led cmd-led-${ok ? 'green' : 'amber'}`} /></td>
      <td className="soft" style={{ fontSize: 12.5 }}>{k}</td>
      <td className="mono" style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--dir-accent)' }}>{v}</td>
      <td className="mono" style={{ fontSize: 10, color: 'var(--text-mute)' }}>{note}</td>
    </tr>
  )
}

function signed(n: number) { return `${n >= 0 ? '+' : '−'}$${Math.abs(n).toFixed(2)}` }
