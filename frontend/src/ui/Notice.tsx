import type { ReactNode } from 'react'
import { AlertCircle, AlertTriangle, Info } from 'lucide-react'
import { cn } from './cn'

type Tone = 'info' | 'warn' | 'error'

const TONES: Record<Tone, { className: string; Icon: typeof Info }> = {
  info: { className: 'border-line bg-surface text-fg-2', Icon: Info },
  warn: { className: 'border-warn/30 bg-warn/8 text-fg-2', Icon: AlertTriangle },
  error: { className: 'border-bad/30 bg-bad/8 text-fg-2', Icon: AlertCircle },
}

/** An inline message that says what happened and what to do next. */
export function Notice({ tone = 'info', title, children, className }: {
  tone?: Tone
  title?: ReactNode
  children?: ReactNode
  className?: string
}) {
  const { className: toneClass, Icon } = TONES[tone]
  return (
    <div className={cn('flex gap-3 rounded-xl border px-4 py-3 text-[13px]', toneClass, className)} role={tone === 'error' ? 'alert' : undefined}>
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', tone === 'error' ? 'text-bad' : tone === 'warn' ? 'text-warn' : 'text-fg-3')} aria-hidden="true" />
      <div className="grid min-w-0 gap-0.5">
        {title && <p className="font-medium text-fg">{title}</p>}
        {children && <div className="[&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_code]:font-mono [&_code]:text-[12px]">{children}</div>}
      </div>
    </div>
  )
}
