import type { ReactNode } from 'react'
import { cn } from './cn'

/** Page title plus the one question the page answers, so pages with similar data stay distinct. */
export function PageHeader({ title, description, actions, className }: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <header className={cn('flex flex-wrap items-end justify-between gap-4 pb-6', className)}>
      <div className="grid max-w-2xl gap-1.5">
        <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-fg">{title}</h1>
        {description && <p className="text-fg-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
