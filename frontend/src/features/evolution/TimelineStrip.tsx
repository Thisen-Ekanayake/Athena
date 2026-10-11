import { Pin } from 'lucide-react'
import { cn } from '../../ui/cn'
import type { EvolutionTimeline } from './api'

interface TimelineStripProps {
  timeline: EvolutionTimeline
  selectedId: string | null
  onSelect: (id: string) => void
}

/** Milestones by year, oldest first. Each one selects the paper in the map. */
export function TimelineStrip({ timeline, selectedId, onSelect }: TimelineStripProps) {
  if (timeline.years.length === 0) {
    return <p className="text-[13px] text-fg-3">No milestones yet. Build the topic, or pin papers from the map.</p>
  }
  return (
    <div className="overflow-x-auto pb-2">
      <ol className="flex min-w-max gap-3">
        {timeline.years.map(({ year, papers }) => (
          <li key={year} className="flex w-44 shrink-0 flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[12px] font-medium text-accent tabular-nums">{year}</span>
              <span className="h-px flex-1 bg-line" />
            </div>
            {papers.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onSelect(p.id)}
                title={p.title}
                aria-pressed={selectedId === p.id}
                className={cn(
                  'rounded-lg border px-2.5 py-1.5 text-left text-[12.5px] leading-snug transition-colors',
                  selectedId === p.id ? 'border-accent-line bg-accent-soft text-fg' : 'border-line bg-surface text-fg-2 hover:border-line-strong hover:text-fg',
                )}
              >
                <span className="line-clamp-2">
                  {p.milestone_override === 'pin' && <Pin className="mr-1 mb-0.5 inline h-3 w-3 text-accent" aria-label="Pinned by you" />}
                  {p.named_method ?? p.title}
                </span>
              </button>
            ))}
          </li>
        ))}
      </ol>
    </div>
  )
}
