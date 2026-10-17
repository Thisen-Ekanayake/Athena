import { useScoreBreakdown } from '../../api/queries/score'
import { timeAgo } from '../items/format'
import { Spinner } from '../../ui/Spinner'

/** The signals behind an item's relevance score, each with its weight. */
export function ScoreBreakdown({ itemId }: { itemId: string }) {
  const { data, isLoading, error } = useScoreBreakdown(itemId, true)

  if (isLoading) return <Spinner label="Loading the score…" />
  if (error || !data) return <p className="text-[13px] text-fg-3">This item has not been scored yet.</p>

  // A signal with no weight for this kind of item (no data for it) is left out
  const shared = data.signals.filter((s) => s.key !== 'your_interests' && s.weight > 0)
  const mine = data.signals.find((s) => s.key === 'your_interests')

  return (
    <div className="grid gap-2.5">
      {shared.map((s) => <SignalRow key={s.key} label={s.label} note={`weight ${Math.round(s.weight * 100)}%`} value={s.value} max={s.max_value} />)}
      <p className="text-[12px] text-fg-3">Scored {timeAgo(data.computed_at)}</p>
      {mine && (
        <div className="grid gap-1.5 border-t border-line pt-2.5">
          <SignalRow label={mine.label} note={`${Math.round(mine.weight * 100)}% of your For-you order`} value={mine.value} max={mine.max_value} />
          <p className="text-[12px] text-fg-3">How close it is to what you liked and saved, against the rest of your feed. Only you see this; the score above is everyone's.</p>
        </div>
      )}
    </div>
  )
}

function SignalRow({ label, note, value, max }: { label: string; note: string; value: number; max: number }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_96px_36px] items-center gap-3 text-[12.5px]">
      <span className="text-fg-2">
        {label} <span className="text-fg-3">· {note}</span>
      </span>
      <span className="h-1.5 overflow-hidden rounded-full bg-surface-3">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round((value / max) * 100)}%` }} />
      </span>
      <span className="text-right font-mono tabular-nums text-fg-2">{value.toFixed(2)}</span>
    </div>
  )
}
