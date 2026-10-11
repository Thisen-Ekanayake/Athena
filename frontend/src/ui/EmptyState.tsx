import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from './cn'

export function EmptyState({ icon: Icon, title, children, action, className }: {
  icon?: LucideIcon
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center gap-2 rounded-xl border border-dashed border-line px-6 py-14 text-center', className)}>
      {Icon && <Icon className="mb-1 h-6 w-6 text-fg-3" aria-hidden="true" />}
      <p className="font-medium text-fg">{title}</p>
      {children && <div className="max-w-sm text-[13px] text-fg-2">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}
