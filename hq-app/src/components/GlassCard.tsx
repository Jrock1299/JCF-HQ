import { motion } from 'framer-motion'
import type { ReactNode, CSSProperties } from 'react'

type Tint = 'plain' | 'gold' | 'purple' | 'blue' | 'green'

const tintClass: Record<Tint, string> = {
  plain: 'glass',
  gold: 'glass-gold',
  purple: 'glass-purple',
  blue: 'glass-blue',
  green: 'glass-green',
}

interface Props {
  children: ReactNode
  tint?: Tint
  hover?: boolean
  className?: string
  style?: CSSProperties
  onClick?: () => void
  delay?: number
}

export default function GlassCard({
  children,
  tint = 'plain',
  hover = true,
  className = '',
  style,
  onClick,
  delay = 0,
}: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: [0.22, 1, 0.36, 1] }}
      className={`${tintClass[tint]} ${hover ? 'glass-hover' : ''} ${className}`}
      style={{ padding: 20, ...style }}
      onClick={onClick}
    >
      {children}
    </motion.div>
  )
}
