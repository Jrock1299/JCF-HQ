import type { ReactNode } from 'react'
import GlassCard from './GlassCard'
import MiniSparkline from './MiniSparkline'

interface Props {
  label: string
  value: ReactNode
  sub?: ReactNode
  spark?: number[]
  sparkColor?: string
  valueColor?: string
  tint?: 'plain' | 'gold' | 'purple' | 'blue' | 'green'
  gradient?: boolean
  delay?: number
  children?: ReactNode
}

export default function StatCard({
  label,
  value,
  sub,
  spark,
  sparkColor = 'var(--gold)',
  valueColor,
  tint = 'plain',
  gradient = false,
  delay = 0,
  children,
}: Props) {
  return (
    <GlassCard tint={tint} delay={delay} style={{ display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}>
      <div className="mono-label">{label}</div>
      <div
        className={`stat-num ${gradient ? 'gold-text' : ''}`}
        style={{ fontSize: 26, color: gradient ? undefined : valueColor || 'var(--text-hi)', wordBreak: 'break-word' }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{sub}</div>}
      {children}
      {spark && spark.length > 1 && (
        <div style={{ marginTop: 'auto', paddingTop: 6 }}>
          <MiniSparkline data={spark} color={sparkColor} width={999} height={34} />
        </div>
      )}
    </GlassCard>
  )
}
