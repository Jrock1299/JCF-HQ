import { AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import GlassCard from '../components/GlassCard'
import EditableValue from '../components/EditableValue'
import ApiCostCard from '../components/ApiCostCard'
import { useHQData, fmtUSD, timeAgo } from '../hooks/useHQData'
import { trajectory } from '../data/derive'

const SPEC = { netWorth: 958000, goal: 10_000_000, robinhood: 13_500 }

export default function Finances() {
  const nw = useHQData('net-worth').data
  const plaid = useHQData('plaid-data').data
  const tx = useHQData('plaid-transactions').data
  const tao = useHQData('tao-portfolio').data
  const rh = useHQData('robinhood').data
  const kraken = useHQData('kraken').data
  const mercury = useHQData('mercury').data

  const netWorth = nw?.networth_override ?? SPEC.netWorth
  const goalPct = (netWorth / SPEC.goal) * 100
  const remaining = SPEC.goal - netWorth

  const chartData = trajectory(Math.round(netWorth * 0.72), netWorth, 12)

  // accounts (Plaid is index-addressable: 0 = checking, 1 = MMA)
  const checking = plaid?.accounts?.[0]?.balance
  const mma = plaid?.accounts?.[1]?.balance
  // sync_robinhood.py writes total_equity + last_update (older shapes kept as fallbacks)
  const rhVal = rh?.total_equity ?? rh?.total_value ?? rh?.balance ?? SPEC.robinhood
  const krakenVal = kraken?.total_usd ?? null
  const mercuryVal = mercury?.balance ?? null
  const mercuryName = mercury?.account_name ?? 'Mercury Business'
  const taoAmt = tao?.root_staked_tao ?? 3.345
  const taoUsd = tao?.tao_price_usd ? taoAmt * tao.tao_price_usd : null

  // Round 2: TradeLocker removed · Trust Wallet → Kraken · + Mercury (business)
  const accounts = [
    { name: 'Truist Checking', emoji: '🏦', balance: checking, color: 'green', sync: plaid?.updated, file: 'plaid_data.json', path: 'accounts.0.balance' },
    { name: 'Truist MMA', emoji: '💰', balance: mma, color: 'green', sync: plaid?.updated, file: 'plaid_data.json', path: 'accounts.1.balance' },
    { name: 'Robinhood', emoji: '📈', balance: rhVal, color: 'blue', sync: rh?.last_update ?? rh?.updated, file: 'robinhood_data.json', path: 'total_equity' },
    { name: 'Kraken', emoji: '🐙', balance: krakenVal, color: 'purple', sync: kraken?.last_updated, file: 'kraken_data.json', path: 'total_usd' },
    { name: 'Mercury', emoji: '🏛️', balance: mercuryVal, sub: mercuryName, color: 'blue', sync: mercury?.last_updated, file: 'mercury_data.json', path: 'balance' },
    { name: 'Tao Staking', emoji: '☯️', balance: taoUsd, sub: `${taoAmt} TAO`, color: 'purple', sync: tao?.updated, file: 'tao_portfolio.json', path: 'manual_usd_value' },
  ]

  // income vs expenses
  const incomeYtd = tx?.income_ytd ?? null
  const incomeMo = tx?.income_this_month ?? null
  const expensesMo = tx?.expenses_this_month ?? null
  const monthly = buildMonthly(tx?.transactions)

  return (
    <div className="page-pad">
      {/* Net worth hero */}
      <GlassCard tint="gold" hover={false} style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.1fr', gap: 28, alignItems: 'center' }}>
          <div>
            <div className="mono-label" style={{ marginBottom: 12 }}>total net worth</div>
            <EditableValue
              file="net_worth.json"
              path="networth_override"
              value={netWorth}
              type="number"
              display={(v) => fmtUSD(Number(v) || 0)}
              className="hero-num gold-text"
              style={{ fontSize: 52 }}
            />
            <div style={{ marginTop: 18, position: 'relative' }}>
              <div className="bar-track" style={{ height: 8 }}>
                <div className="bar-fill" style={{ width: `${Math.min(100, goalPct)}%`, background: 'linear-gradient(90deg,#d4a843,#f0c060)' }} />
              </div>
              <div style={{ position: 'relative', height: 0 }}>
                {[10, 20, 30, 40, 50, 60, 70, 80, 90].map((p) => (
                  <span key={p} style={{ position: 'absolute', left: `${p}%`, top: -8, width: 1, height: 8, background: 'rgba(7,8,15,0.6)' }} />
                ))}
              </div>
            </div>
            <div className="mono" style={{ marginTop: 12, fontSize: 12, color: 'var(--text-dim)' }}>
              {goalPct.toFixed(1)}% to $10M · <span className="text-gold">{fmtUSD(remaining)}</span> to go
            </div>
          </div>
          <div style={{ height: 200 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 6, right: 6, left: -12, bottom: 0 }}>
                <defs>
                  <linearGradient id="nwFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#d4a843" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#d4a843" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="m" tick={{ fill: 'rgba(240,237,230,0.4)', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: 'rgba(240,237,230,0.4)', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip content={<Tip />} />
                <Area type="monotone" dataKey="v" stroke="#d4a843" strokeWidth={2} fill="url(#nwFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </GlassCard>

      {/* Accounts grid */}
      <div className="mono-label" style={{ marginBottom: 12 }}>accounts</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14, marginBottom: 24 }}>
        {accounts.map((a, i) => (
          <GlassCard key={a.name} delay={i * 0.04}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 500 }}>{a.emoji} {a.name}</div>
                <div style={{ marginTop: 10 }}>
                  <EditableValue
                    file={a.file}
                    path={a.path}
                    value={a.balance ?? 0}
                    type="number"
                    display={(v) => fmtUSD(Number(v) || 0)}
                    className={`stat-num text-${a.color}`}
                    style={{ fontSize: 24 }}
                  />
                </div>
                {a.sub && <div className="mono" style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>{a.sub}</div>}
              </div>
              <span className="text-green" style={{ fontSize: 13 }}>▲</span>
            </div>
            <div className="mono-meta" style={{ marginTop: 12 }}>synced {timeAgo(a.sync)}</div>
          </GlassCard>
        ))}
      </div>

      {/* Income vs expenses */}
      <div className="mono-label" style={{ marginBottom: 12 }}>income vs expenses</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        <GlassCard tint="green" hover={false}>
          <div className="mono-label" style={{ marginBottom: 8 }}>income · ytd</div>
          <div className="stat-num text-green" style={{ fontSize: 30 }}>{fmtUSD(incomeYtd)}</div>
          <div className="mono-meta" style={{ marginTop: 6 }}>this month {fmtUSD(incomeMo)}</div>
        </GlassCard>
        <GlassCard hover={false} style={{ background: 'rgba(239,68,68,0.06)', border: '0.5px solid rgba(239,68,68,0.18)' }}>
          <div className="mono-label" style={{ marginBottom: 8 }}>expenses · this month</div>
          <div className="stat-num text-red" style={{ fontSize: 30 }}>{fmtUSD(expensesMo)}</div>
          <div className="mono-meta" style={{ marginTop: 6 }}>{monthly.length} months tracked</div>
        </GlassCard>
      </div>

      <GlassCard hover={false}>
        <div className="mono-label" style={{ marginBottom: 14 }}>monthly cash flow</div>
        {monthly.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>No transaction history synced yet.</div>
        ) : (
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={monthly} margin={{ top: 4, right: 6, left: -12, bottom: 0 }}>
                <defs>
                  <linearGradient id="incomeFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22c55e" stopOpacity={0.45} />
                    <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="expenseFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.4} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="m" tick={{ fill: 'rgba(240,237,230,0.4)', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: 'rgba(240,237,230,0.4)', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                <Tooltip content={<Tip />} cursor={{ stroke: 'rgba(255,255,255,0.12)' }} />
                <Area type="monotone" dataKey="income" stroke="#22c55e" strokeWidth={2} fill="url(#incomeFill)" style={{ filter: 'drop-shadow(0 0 6px rgba(34,197,94,0.4))' }} />
                <Area type="monotone" dataKey="expenses" stroke="#ef4444" strokeWidth={2} fill="url(#expenseFill)" style={{ filter: 'drop-shadow(0 0 6px rgba(239,68,68,0.35))' }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </GlassCard>

      {/* API usage & cost */}
      <div className="mono-label" style={{ margin: '24px 0 12px' }}>api usage &amp; cost</div>
      <ApiCostCard />
    </div>
  )
}

function buildMonthly(transactions: any[]): { m: string; income: number; expenses: number }[] {
  if (!Array.isArray(transactions)) return []
  const buckets: Record<string, { income: number; expenses: number }> = {}
  for (const t of transactions) {
    const d = new Date(t.date)
    if (Number.isNaN(d.getTime())) continue
    const key = d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
    if (!buckets[key]) buckets[key] = { income: 0, expenses: 0 }
    const amt = Number(t.amount) || 0
    const isIncome = String(t.type).toLowerCase() === 'income' || amt < 0
    if (isIncome) buckets[key].income += Math.abs(amt)
    else buckets[key].expenses += Math.abs(amt)
  }
  return Object.entries(buckets)
    .map(([m, v]) => ({ m, ...v }))
    .slice(-6)
}

function Tip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="glass" style={{ padding: '8px 12px', fontSize: 12 }}>
      <div className="mono" style={{ color: 'var(--text-dim)', marginBottom: 3 }}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="mono" style={{ color: p.color || 'var(--gold)' }}>{p.dataKey}: {fmtUSD(p.value)}</div>
      ))}
    </div>
  )
}
