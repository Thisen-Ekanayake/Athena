import { cn } from '../../ui/cn'

/**
 * How full the model's context is, as a ring that fills: the conversation so far (the last answer's prompt and
 * reply) against the context size picked. Hovered or focused, it says how many tokens of how many.
 */
export function ContextMeter({ used, total, estimated }: { used: number; total: number; estimated?: boolean }) {
  const share = total > 0 ? used / total : 0
  const pct = Math.round(share * 100)
  const r = 7
  const length = 2 * Math.PI * r
  const tone = share > 1 ? 'text-bad' : share > 0.8 ? 'text-warn' : 'text-accent'
  const label = `${estimated ? 'About ' : ''}${used.toLocaleString()} / ${total.toLocaleString()} tokens of context used (${pct}%)`
  return (
    <span className="group relative inline-flex">
      <button type="button" aria-label={label} className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-surface-2 focus-visible:bg-surface-2">
        <svg viewBox="0 0 18 18" className="h-[18px] w-[18px] -rotate-90" aria-hidden="true">
          <circle cx="9" cy="9" r={r} fill="none" strokeWidth="2.5" className="stroke-surface-3" />
          <circle cx="9" cy="9" r={r} fill="none" strokeWidth="2.5" strokeLinecap="round" stroke="currentColor"
            className={cn('transition-[stroke-dasharray] duration-500', tone)}
            strokeDasharray={`${Math.min(share, 1) * length} ${length}`} />
        </svg>
      </button>
      <span role="tooltip" className="pointer-events-none absolute right-0 bottom-full z-20 mb-2 hidden w-60 rounded-lg border border-line bg-surface px-3 py-2 text-[12px] shadow-pop group-hover:block group-focus-within:block">
        <span className="block font-mono text-fg">{estimated ? '~' : ''}{used.toLocaleString()} / {total.toLocaleString()} tokens</span>
        <span className="block text-fg-3">
          {share > 1 ? 'More than this context holds: the oldest turns are left out. Pick a larger context to keep them.'
            : `${pct}% of the context used${share > 0.8 ? '; older turns will soon be left out' : ''}.`}
        </span>
      </span>
    </span>
  )
}
