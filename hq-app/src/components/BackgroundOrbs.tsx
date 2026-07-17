import { motion } from 'framer-motion'

// Three fixed radial-gradient blobs drifting slowly behind all content.
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
        background: 'radial-gradient(circle at 50% 120%, #0d0f1a 0%, #07080f 60%)',
      }}
    >
      <motion.div
        style={{ ...orb, top: '-12%', left: '-8%', background: 'radial-gradient(circle, rgba(124,58,237,0.18), transparent 65%)' }}
        animate={{ x: [0, 60, -20, 0], y: [0, 40, 70, 0] }}
        transition={{ duration: 11, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        style={{ ...orb, top: '-14%', right: '-10%', background: 'radial-gradient(circle, rgba(212,168,67,0.12), transparent 65%)' }}
        animate={{ x: [0, -50, 20, 0], y: [0, 50, 20, 0] }}
        transition={{ duration: 9, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.div
        style={{ ...orb, bottom: '-18%', left: '35%', background: 'radial-gradient(circle, rgba(14,165,233,0.10), transparent 65%)' }}
        animate={{ x: [0, 40, -40, 0], y: [0, -30, 20, 0] }}
        transition={{ duration: 12, repeat: Infinity, ease: 'easeInOut' }}
      />
    </div>
  )
}

const orb: React.CSSProperties = {
  position: 'absolute',
  width: '46vw',
  height: '46vw',
  maxWidth: 760,
  maxHeight: 760,
  filter: 'blur(40px)',
  borderRadius: '50%',
}
