import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from './cn'

/** Page numbers with previous and next, for a list shown a page at a time. Nothing when it fits on one page. */
export function Pager({ page, pages, onChange, label, className }: {
  page: number
  pages: number
  onChange: (page: number) => void
  label: string
  className?: string
}) {
  if (pages <= 1) return null
  const step = 'inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1.5 text-[12px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-fg disabled:pointer-events-none disabled:opacity-40 [&_svg]:h-3.5 [&_svg]:w-3.5'
  return (
    <nav aria-label={label} className={cn('flex items-center gap-0.5', className)}>
      <button type="button" className={step} disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page"><ChevronLeft /></button>
      {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
        <button key={n} type="button" onClick={() => onChange(n)} aria-label={`Page ${n}`} aria-current={n === page ? 'page' : undefined}
          className={cn(step, 'font-mono', n === page && 'bg-surface-2 text-fg shadow-[0_0_0_1px_var(--line)]')}>
          {n}
        </button>
      ))}
      <button type="button" className={step} disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Next page"><ChevronRight /></button>
    </nav>
  )
}
