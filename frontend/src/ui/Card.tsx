import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from './cn'

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn('rounded-xl border border-line bg-surface', className)}>{children}</section>
}

export function CardHeader({ icon: Icon, title, action, className }: {
  icon?: LucideIcon
  title: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <header className={cn('flex items-center justify-between gap-3 px-4 pt-3.5 pb-2', className)}>
      <h2 className="flex items-center gap-2 text-[13px] font-medium text-fg">
        {Icon && <Icon className="h-[15px] w-[15px] text-fg-3" aria-hidden="true" />}
        {title}
      </h2>
      {action}
    </header>
  )
}
