import { useScoreBreakdown } from '../../api/queries/phase4'
import { timeAgo } from '../items/format'
import { Spinner } from '../../ui/Spinner'

/** The signals behind an item's relevance score, each with its weight. */
export function ScoreBreakdown({ itemId }: { itemId: string }) {
  const { data, isLoading, error } = useScoreBreakdown(itemId, true)

  if (isLoading) return <Spinner label="Loading the score…" />
  if (error || !data) return <p className="text-[13px] text-fg-3">This item has not been scored yet.</p>

  return (
    <div className="grid gap-2.5">
      {data.signals.map((s) => (
        <div key={s.label} className="grid grid-cols-[minmax(0,1fr)_96px_36px] items-center gap-3 text-[12.5px]">
          <span className="text-fg-2">
            {s.label} <span className="text-fg-3">· weight {Math.round(s.weight * 100)}%</span>
          </span>
          <span className="h-1.5 overflow-hidden rounded-full bg-surface-3">
            <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round((s.value / s.max_value) * 100)}%` }} />
          </span>
          <span className="text-right font-mono tabular-nums text-fg-2">{s.value.toFixed(2)}</span>
        </div>
      ))}
      <p className="text-[12px] text-fg-3">Scored {timeAgo(data.computed_at)}</p>
    </div>
  )
}
