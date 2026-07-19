import { motion } from 'framer-motion'

// Ambient background: a moonlight sweep from top-center + three softly
// drifting orbs (dialed back — ambiance, not the main event). Theme-aware via
// CSS vars (--bg-deep, --bg-mid, --moonlight, --orb-opacity).
export default function BackgroundOrbs() {
  return (
    <div
      aria-hidden
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        overflow: 'hidden',
        pointerEvents: 'none',
        background: 'radial-gradient(circle at 50% 120%, var(--bg-mid) 0%, var(--bg-deep) 62%)',
        transition: 'background 0.3s ease',
      }}
    >
      {/* Moonlight sweep — a broad soft light falling from top-center */}
      <div
        style={{
          position: 'absolute',
          top: '-30%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '120vw',
          height: '90vh',
          background: 'radial-gradient(ellipse at center, var(--moonlight) 0%, transparent 60%)',
          pointerEvents: 'none',
        }}
      />
      <div style={{ opacity: 'var(--orb-opacity)' as any, position: 'absolute', inset: 0 }}>
        <motion.div
          style={{ ...orb, top: '-12%', left: '-8%', background: 'radial-gradient(circle, rgba(124,58,237,0.16), transparent 65%)' }}
          animate={{ x: [0, 60, -20, 0], y: [0, 40, 70, 0] }}
          transition={{ duration: 13, repeat: Infinity, ease: 'easeInOut' }}
        />
        <motion.div
          style={{ ...orb, top: '-14%', right: '-10%', background: 'radial-gradient(circle, rgba(212,168,67,0.10), transparent 65%)' }}
          animate={{ x: [0, -50, 20, 0], y: [0, 50, 20, 0] }}
          transition={{ duration: 11, repeat: Infinity, ease: 'easeInOut' }}
        />
        <motion.div
          style={{ ...orb, bottom: '-18%', left: '35%', background: 'radial-gradient(circle, rgba(14,165,233,0.09), transparent 65%)' }}
          animate={{ x: [0, 40, -40, 0], y: [0, -30, 20, 0] }}
          transition={{ duration: 14, repeat: Infinity, ease: 'easeInOut' }}
        />
      </div>
    </div>
  )
}

const orb: React.CSSProperties = {
  position: 'absolute',
  width: '42vw',
  height: '42vw',
  maxWidth: 700,
  maxHeight: 700,
  filter: 'blur(32px)',
  borderRadius: '50%',
  // Promote each animated orb to its own compositor layer so the drift
  // animation stays on the GPU (transforms only — no layout/paint per frame).
  willChange: 'transform',
}
