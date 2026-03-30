import { motion } from 'framer-motion'
import { useEffect, useState } from 'react'

interface ScoreRingProps {
  score: number // 0 to 1
  size?: number
  strokeWidth?: number
}

export function ScoreRing({ score, size = 42, strokeWidth = 3 }: ScoreRingProps) {
  const [isMounted, setIsMounted] = useState(false)
  const percentage = Math.round(score * 100)
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score * circumference)

  useEffect(() => {
    const timer = setTimeout(() => setIsMounted(true), 120)
    return () => clearTimeout(timer)
  }, [])

  const getColor = () => {
    if (percentage >= 80) return 'var(--color-accent-success)'
    if (percentage >= 50) return 'var(--color-accent-warning)'
    return 'var(--color-accent-critical)'
  }

  const getGlow = () => {
    if (percentage >= 80) return '0 0 12px rgba(61, 214, 140, 0.3)'
    if (percentage >= 50) return '0 0 12px rgba(224, 169, 75, 0.3)'
    return '0 0 12px rgba(224, 90, 107, 0.3)'
  }

  return (
    <div 
      className="relative flex items-center justify-center select-none"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="transform -rotate-90">
        {/* Background Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="rgba(255,255,255,0.05)"
          strokeWidth={strokeWidth}
          fill="transparent"
        />
        {/* Progress Ring */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={getColor()}
          strokeWidth={strokeWidth}
          fill="transparent"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={isMounted ? { strokeDashoffset: offset } : {}}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(${getGlow()})` }}
        />
      </svg>
      <div 
        className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium transition-colors duration-300"
        style={{ color: getColor() }}
      >
        {percentage}
      </div>
    </div>
  )
}
