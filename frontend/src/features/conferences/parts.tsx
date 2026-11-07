import { useState } from 'react'
import { ArrowDown, ArrowUp, Award } from 'lucide-react'
import { CONF_KINDS, type ConfKind, type ConfPaperBrief, type ConfTopicShare } from '../../api/queries/conferences'
import { Chip } from '../../ui/Chip'
import { cn } from '../../ui/cn'
import { KIND_LABEL, pct } from './format'

/** A change in share, in percentage points, with its direction as an arrow (never colour alone). */
export function Change({ change, className }: { change: number | null | undefined; className?: string }) {
  if (change === null || change === undefined) {
    return <span className={cn('text-fg-3', className)} title="The previous edition has no papers sorted into topics yet">–</span>
  }
  const points = change * 100
  if (Math.abs(points) < 0.05) return <span className={cn('text-fg-3', className)}>±0</span>
  const Icon = points > 0 ? ArrowUp : ArrowDown
  return (
    <span className={cn('inline-flex items-center gap-0.5 font-mono tabular-nums text-fg-2', className)}
      title={`${points > 0 ? 'Up' : 'Down'} ${Math.abs(points).toFixed(1)} percentage points since the previous edition`}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      <span className="sr-only">{points > 0 ? 'up' : 'down'}</span>
      {Math.abs(points).toFixed(1)}
    </span>
  )
}

/** Which kinds of papers count: main proceedings, Findings, journals. At least one stays on. */
export function KindsToggle({ value, onChange, available }: {
  value: ConfKind[]
  onChange: (kinds: ConfKind[]) => void
  available?: ConfKind[]
}) {
  const shown = CONF_KINDS.filter((k) => !available || available.includes(k.value) || value.includes(k.value))
  return (
    <div role="group" aria-label="Papers to count" className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
      {shown.map((k) => {
        const on = value.includes(k.value)
        return (
          <button key={k.value} type="button" aria-pressed={on}
            onClick={() => {
              const next = on ? value.filter((v) => v !== k.value) : [...value, k.value]
              if (next.length) onChange(CONF_KINDS.map((c) => c.value).filter((c) => next.includes(c)))
            }}
            className={cn('inline-flex h-6 items-center rounded-md px-2.5 text-[12.5px] text-fg-2 transition-colors hover:text-fg',
              on && 'bg-surface text-fg shadow-[0_0_0_1px_var(--line)]')}>
            {k.label}
          </button>
        )
      })}
    </div>
  )
}

/** Each topic's share of an edition as a bar (one hue: it is magnitude), with papers and the change since the
 * previous edition as text beside it. A row is a button that opens the topic's papers. */
export function TopicShares({ topics, onPick, picked, limit }: {
  topics: ConfTopicShare[]
  onPick: (id: number) => void
  picked?: number | null
  limit?: number
}) {
  const [all, setAll] = useState(false)
  const rows = topics.filter((t) => t.papers > 0)
  const shown = all || !limit ? rows : rows.slice(0, limit)
  const top = Math.max(...rows.map((t) => t.share), 0.0001)
  if (!rows.length) return <p className="px-4 pb-4 text-[13px] text-fg-3">No papers are sorted into topics yet.</p>
  return (
    <div className="px-2 pb-2">
      <ul className="grid">
        {shown.map((t) => (
          <li key={t.id}>
            <button type="button" onClick={() => onPick(t.id)} aria-pressed={picked === t.id}
              className={cn('grid w-full grid-cols-[minmax(0,13rem)_1fr_auto] items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-2 max-sm:grid-cols-[1fr_auto]',
                picked === t.id && 'bg-surface-2')}>
              <span className="truncate text-[13px] text-fg" title={t.name}>{t.name}</span>
              <span className="relative h-2 rounded-full max-sm:hidden" aria-hidden="true">
                <span className="absolute inset-y-0 left-0 rounded-full bg-accent"
                  style={{ width: `max(3px, ${(t.share / top) * 100}%)` }} />
              </span>
              <span className="flex items-center gap-3 text-[12px]">
                <span className="w-12 text-right font-mono tabular-nums text-fg">{pct(t.share)}</span>
                <span className="w-12 text-right font-mono tabular-nums text-fg-3" title="Papers">{t.papers.toLocaleString()}</span>
                <Change change={t.change} className="w-12 justify-end text-right" />
              </span>
            </button>
          </li>
        ))}
      </ul>
      {limit && rows.length > limit && (
        <button type="button" onClick={() => setAll(!all)} className="mt-1 px-2 text-[12.5px] text-fg-2 hover:text-fg">
          {all ? 'Fewer topics' : `All ${rows.length} topics`}
        </button>
      )}
    </div>
  )
}

export function AwardChips({ awards }: { awards: string[] }) {
  if (!awards.length) return null
  return (
    <>
      {awards.map((a) => <Chip key={a} tone="accent"><Award aria-hidden="true" />{a}</Chip>)}
    </>
  )
}

/** One paper in a list: title (opens the panel), authors, kind, awards and citations. */
export function PaperRow({ paper, onOpen, rank }: { paper: ConfPaperBrief; onOpen: (id: string) => void; rank?: number }) {
  const more = paper.author_count - paper.authors.length
  return (
    <li className="flex gap-3 border-b border-line px-4 py-3 last:border-b-0">
      {rank !== undefined && <span className="w-6 shrink-0 pt-px text-right font-mono text-[12px] tabular-nums text-fg-3">{rank}</span>}
      <div className="grid min-w-0 flex-1 gap-1">
        <button type="button" onClick={() => onOpen(paper.id)} className="text-left text-[13.5px] font-medium leading-snug text-fg hover:text-accent-ink">
          {paper.title}
        </button>
        <p className="truncate text-[12.5px] text-fg-2">
          {paper.authors.join(', ')}{more > 0 ? ` +${more}` : ''}
        </p>
        <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
          <span className="font-mono tabular-nums">{paper.year}</span>
          {paper.kind && <Chip>{KIND_LABEL[paper.kind]}</Chip>}
          {paper.topic && <span className="truncate">{paper.topic.name}</span>}
          <AwardChips awards={paper.awards} />
        </div>
      </div>
      <div className="shrink-0 pt-px text-right">
        <p className="font-mono text-[13px] tabular-nums text-fg">{paper.citation_count?.toLocaleString() ?? '–'}</p>
        <p className="text-[11px] text-fg-3">citations</p>
      </div>
    </li>
  )
}
