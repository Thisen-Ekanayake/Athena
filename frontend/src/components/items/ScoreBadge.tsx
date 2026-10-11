import { cn } from '../../ui/cn'
import { formatScore } from './format'

/** The composite relevance score, 0 to 1. Scores of 0.8 and above get the accent. */
export function ScoreBadge({ score, className }: { score: number; className?: string }) {
  return (
    <span
      title="Relevance score"
      className={cn(
        'inline-flex h-[22px] items-center rounded-md px-1.5 font-mono text-[12px] font-medium tabular-nums',
        score >= 0.8 ? 'bg-accent-soft text-accent-ink' : 'bg-surface-2 text-fg-2',
        className,
      )}
    >
      {formatScore(score)}
    </span>
  )
}
