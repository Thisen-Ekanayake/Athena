import type { ReactNode } from 'react'
import { cn } from './cn'

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cn('inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-line bg-surface-2 px-1 font-mono text-[11px] leading-none text-fg-3', className)}>
      {children}
    </kbd>
  )
}
