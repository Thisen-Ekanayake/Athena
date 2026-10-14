import { useState, type ReactNode } from 'react'
import { BookOpenText, CheckCircle2, CircleDot, MoonStar, RefreshCw, Sparkle } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { useIsAdmin } from '../../api/queries/auth'
import { timeAgo } from '../../components/items/format'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { RisingInMap } from './RisingInMap'
import {
  useMapScope,
  useReadFullText,
  useTopicSettings,
  useRefreshTopic,
  useTopicChanges,
  type ChangedTheme,
  type MapSnapshot,
} from './api'

const REASONS: Record<MapSnapshot['reason'], string> = {
  baseline: 'First record',
  build: 'Rebuilt',
  refresh: 'Refreshed',
  full_text: 'Full text read',
}

const INTERVALS = [0, 7, 14, 30, 60, 90]

interface ChangesViewProps {
  slug: string
  busy: boolean
  onSelect: (id: string) => void
}

/** What changed in this map between builds and refreshes, newest first; admins keep it up to date from here. */
export function ChangesView({ slug, busy, onSelect }: ChangesViewProps) {
  const { data, isLoading, error } = useTopicChanges(slug)
  const isAdmin = useIsAdmin()
  const { readOnly } = useMapScope()  // a shared link shows what changed, not how the map is kept up
  if (isLoading) return <Spinner label="Loading the changes…" />
  if (error || !data) return <Notice tone="error" title="The changes could not be loaded">Check that the API is running.</Notice>
  return (
    <div className="grid max-w-4xl gap-5">
      {readOnly ? null : isAdmin ? <UpkeepPanel slug={slug} refreshDays={data.refresh_days} namedMethod={data.named_method} namedMethodInScores={data.named_method_in_scores} busy={busy} /> : (
        <p className="text-[13px] text-fg-2">
          {data.refresh_days > 0 ? `This map is refreshed every ${data.refresh_days} days: new papers, new full text and new gaps.` : 'This map is not refreshed on a schedule.'}
        </p>
      )}
      <RisingInMap slug={slug} onSelect={onSelect} />
      {data.snapshots.length === 0 ? (
        <Notice title="No changes recorded yet">The first build or refresh records the map’s state; later ones list what changed.</Notice>
      ) : (
        <ol className="grid gap-3">
          {data.snapshots.map((s) => <SnapshotEntry key={s.id} snapshot={s} onSelect={onSelect} />)}
        </ol>
      )}
    </div>
  )
}

interface UpkeepPanelProps {
  slug: string
  refreshDays: number
  namedMethod: boolean
  namedMethodInScores: boolean
  busy: boolean
}

function UpkeepPanel({ slug, refreshDays, namedMethod, namedMethodInScores, busy }: UpkeepPanelProps) {
  const refresh = useRefreshTopic(slug)
  const fullText = useReadFullText(slug)
  const interval = useTopicSettings(slug)
  const [queued, setQueued] = useState<string | null>(null)
  const error = refresh.error ?? fullText.error ?? interval.error
  return (
    <section className="grid gap-3 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[13.5px] font-medium text-fg">Keep this map up to date</h2>
        <label className="ml-auto flex items-center gap-2 text-[12.5px] text-fg-2">
          Refresh
          <select
            value={refreshDays}
            onChange={(e) => interval.mutate({ refresh_days: Number(e.target.value) })}
            disabled={interval.isPending}
            className="h-7 rounded-md border border-line bg-surface-2 px-2 text-[12.5px] text-fg focus:border-accent-line focus:outline-none"
          >
            {[...new Set([...INTERVALS, refreshDays])].sort((a, b) => a - b).map((d) => (
              <option key={d} value={d}>{d === 0 ? 'never' : `every ${d} days`}</option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-[12.5px] leading-relaxed text-fg-2">
        A refresh finds new papers and rebuilds the map (it stays readable meanwhile), reads the open full text of new milestones and their followers, then labels and embeds it on the GPU to update the open problems. It runs at night when due; the first full-text read of a map can keep the GPU busy for an hour or two.
      </p>
      <label className="flex items-start gap-2 text-[12.5px] leading-relaxed text-fg-2">
        <input
          type="checkbox"
          checked={namedMethod}
          disabled={interval.isPending}
          onChange={(e) => interval.mutate({ named_method: e.target.checked })}
          className="mt-1 accent-[var(--accent)]"
        />
        <span>
          Favour papers that later work cites by a method name (“LoRA”, “Faster R-CNN”) when picking milestones.
          Off by default: across the curated maps it lost known milestones on diffusion models and RAG, and gained one on PEFT.
          {namedMethod !== namedMethodInScores && <span className="text-fg-3"> Applies from the next build or refresh.</span>}
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" disabled={busy || refresh.isPending} onClick={() => refresh.mutate(undefined, { onSuccess: () => setQueued('A refresh is queued.') })}>
          <RefreshCw /> Refresh now
        </Button>
        <Button variant="ghost" size="sm" disabled={busy || fullText.isPending} onClick={() => fullText.mutate(undefined, { onSuccess: () => setQueued('Reading the full text is queued; open problems update when the GPU lane finishes.') })}
          title="Read open full text and run the GPU lane, without rebuilding">
          <BookOpenText /> Read full text only
        </Button>
        {busy && <span className="text-[12px] text-fg-3">The map is being built.</span>}
        {queued && <span className="text-[12px] text-fg-2">{queued}</span>}
        {error && <span className="text-[12px] text-bad">{apiErrorMessage(error, 'That did not work')}</span>}
      </div>
    </section>
  )
}

function SnapshotEntry({ snapshot: s, onSelect }: { snapshot: MapSnapshot; onSelect: (id: string) => void }) {
  const c = s.changes
  const nothing = c && !c.new_milestones.length && !c.dropped_milestones.length && !c.papers_added && !c.papers_removed &&
    !c.new_gaps.length && !c.solved_gaps.length && !c.reopened_gaps.length && !c.faded_gaps.length
  return (
    <li className="grid gap-2.5 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[13.5px] font-medium text-fg">{REASONS[s.reason]}</span>
        <time className="text-[12px] text-fg-3" dateTime={s.taken_at} title={new Date(s.taken_at).toLocaleString()}>{timeAgo(s.taken_at)}</time>
        <span className="ml-auto font-mono text-[11.5px] text-fg-3 tabular-nums">
          {s.stats.papers} papers · {s.stats.milestones} milestones · {s.stats.open_themes} open of {s.stats.themes} gap themes
        </span>
      </div>
      {!c ? (
        <p className="text-[12.5px] text-fg-3">The map as it stood; later builds are compared with it.</p>
      ) : nothing ? (
        <p className="text-[12.5px] text-fg-3">Nothing changed.</p>
      ) : (
        <div className="grid gap-2 text-[13px]">
          {c.new_milestones.length > 0 && (
            <Row label="New milestones">
              {c.new_milestones.map((m) => (
                <button key={m.paper_id} type="button" onClick={() => onSelect(m.paper_id)} title={m.title}>
                  <Chip tone="accent" className="hover:opacity-80">{m.named_method ?? m.title} · {m.year ?? 'n.d.'}</Chip>
                </button>
              ))}
            </Row>
          )}
          {c.dropped_milestones.length > 0 && (
            <Row label="No longer milestones">
              {c.dropped_milestones.map((m) => <Chip key={m.paper_id}>{m.named_method ?? m.title}</Chip>)}
            </Row>
          )}
          {(c.papers_added > 0 || c.papers_removed > 0) && (
            <Row label="Papers">
              <span className="text-fg-2">
                {c.papers_added > 0 && `${c.papers_added} added`}{c.papers_added > 0 && c.papers_removed > 0 && ', '}{c.papers_removed > 0 && `${c.papers_removed} dropped`}
                {c.top_new_papers.length > 0 && ', among them '}
              </span>
              {c.top_new_papers.map((p) => (
                <button key={p.paper_id} type="button" onClick={() => onSelect(p.paper_id)} className="text-left text-fg hover:underline">{p.title}{p.year && ` (${p.year})`};</button>
              ))}
            </Row>
          )}
          <Themes label="New gaps" icon={Sparkle} themes={c.new_gaps} />
          <Themes label="A fix is now claimed" icon={CheckCircle2} themes={c.solved_gaps} />
          <Themes label="Stated again" icon={CircleDot} themes={c.reopened_gaps} />
          <Themes label="No longer stated" icon={MoonStar} themes={c.faded_gaps} />
        </div>
      )}
    </li>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-3">
      <span className="text-[12px] text-fg-3">{label}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">{children}</div>
    </div>
  )
}

function Themes({ label, icon: Icon, themes }: { label: string; icon: typeof Sparkle; themes: ChangedTheme[] }) {
  if (!themes.length) return null
  return (
    <Row label={label}>
      {themes.map((t, i) => (
        <Chip key={`${t.label}-${i}`}><Icon aria-hidden="true" />{t.label}</Chip>
      ))}
    </Row>
  )
}
