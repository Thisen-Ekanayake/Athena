import { Loader2 } from 'lucide-react'
import { cn } from './cn'

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-fg-3" role="status">
      <Loader2 className={cn('h-4 w-4 animate-spin', className)} aria-hidden="true" />
      {label && <span className="text-[13px]">{label}</span>}
    </span>
  )
}
