import { motion } from 'framer-motion'
import { useMemo } from 'react'

interface Props {
  data: number[]
  color?: string
  width?: number
  height?: number
  fill?: boolean
}

// Lightweight inline SVG sparkline with a mount draw-in animation. No deps.
export default function MiniSparkline({
  data,
  color = 'var(--gold)',
  width = 120,
  height = 34,
  fill = true,
}: Props) {
  const { line, area } = useMemo(() => {
    if (!data || data.length < 2) return { line: '', area: '' }
    const min = Math.min(...data)
    const max = Math.max(...data)
    const range = max - min || 1
    const step = width / (data.length - 1)
    const pts = data.map((v, i) => {
      const x = i * step
      const y = height - ((v - min) / range) * (height - 4) - 2
      return [x, y] as const
    })
    const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    const area = `${line} L${width},${height} L0,${height} Z`
    return { line, area }
  }, [data, width, height])

  // Keep all hooks before any early return (rules of hooks).
  const gid = useMemo(() => `spark-${Math.floor(Math.abs(data?.[0] || 1) * 1000) % 100000}-${data?.length || 0}`, [data])

  if (!line) return <div style={{ width, height }} />

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: 'block' }}
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${gid})`} />}
      <motion.path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0, opacity: 0.4 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.9, ease: 'easeOut' }}
      />
    </svg>
  )
}
