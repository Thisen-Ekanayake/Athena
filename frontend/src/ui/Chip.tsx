import type { ReactNode } from 'react'
import { cn } from './cn'

export type ChipTone = 'neutral' | 'accent' | 'good' | 'warn' | 'bad'

const TONES: Record<ChipTone, string> = {
  neutral: 'border border-line text-fg-2',
  accent: 'bg-accent-soft text-accent-ink',
  good: 'bg-good/12 text-good',
  warn: 'bg-warn/12 text-warn',
  bad: 'bg-bad/12 text-bad',
}

export function Chip({ tone = 'neutral', className, children }: { tone?: ChipTone; className?: string; children: ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-px text-[11.5px] leading-[18px] [&_svg]:h-3 [&_svg]:w-3', TONES[tone], className)}>
      {children}
    </span>
  )
}
