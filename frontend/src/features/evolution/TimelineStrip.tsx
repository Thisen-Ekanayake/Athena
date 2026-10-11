import type { EvolutionTimeline } from './api'

interface TimelineStripProps {
  timeline: EvolutionTimeline
  selectedId: string | null
  onSelect: (id: string) => void
}

/** Milestones by year, oldest first. Each chip selects the paper in the graph. */
export function TimelineStrip({ timeline, selectedId, onSelect }: TimelineStripProps) {
  if (timeline.years.length === 0) {
    return <p className="text-sm text-text-muted">No milestones yet. Build the topic, or pin papers from the graph.</p>
  }
  return (
    <div className="overflow-x-auto custom-scrollbar pb-2">
      <ol className="flex gap-3 min-w-max">
        {timeline.years.map(({ year, papers }) => (
          <li key={year} className="flex flex-col gap-2 w-44 shrink-0">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-bold text-accent-primary tabular-nums">{year}</span>
              <span className="h-px flex-1 bg-border-subtle" />
            </div>
            {papers.map((p) => (
              <button
                key={p.id}
                onClick={() => onSelect(p.id)}
                title={p.title}
                className={`text-left px-2.5 py-1.5 rounded-md border text-[12px] leading-snug transition-colors ${
                  selectedId === p.id
                    ? 'border-accent-primary/60 bg-accent-primary/15 text-text-primary'
                    : 'border-border-subtle bg-glass-fill text-text-secondary hover:text-text-primary hover:border-accent-primary/30'
                }`}
              >
                <span className="line-clamp-2">
                  {p.milestone_override === 'pin' && <span className="text-accent-warning mr-1">●</span>}
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
