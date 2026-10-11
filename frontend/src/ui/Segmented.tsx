import type { ReactNode } from 'react'
import { cn } from './cn'

interface SegmentedProps<T extends string> {
  label: string
  value: T
  options: { value: T; label: ReactNode; title?: string }[]
  onChange: (value: T) => void
  className?: string
}

/** A row of mutually exclusive options, e.g. a sort order or a date range. */
export function Segmented<T extends string>({ label, value, options, onChange, className }: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} className={cn('inline-flex rounded-lg border border-line bg-surface-2 p-0.5', className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            'inline-flex h-6 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] text-fg-2 transition-colors hover:text-fg [&_svg]:h-3.5 [&_svg]:w-3.5',
            o.value === value && 'bg-surface text-fg shadow-[0_0_0_1px_var(--line)]',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
