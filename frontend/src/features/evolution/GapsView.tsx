import { useMemo, useState } from 'react'
import { CheckCircle2, CircleDot, MoonStar, Sparkle } from 'lucide-react'
import { Chip, type ChipTone } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { useTopicGaps, type GapTheme, type MiniPaper } from './api'

interface GapsViewProps {
  slug: string
  onSelect: (id: string) => void
}

const STATUS: Record<GapTheme['status'], { label: string; icon: typeof CircleDot; tone: ChipTone }> = {
  persisting: { label: 'Persisting', icon: CircleDot, tone: 'warn' },
  new: { label: 'New', icon: Sparkle, tone: 'accent' },
  addressed: { label: 'Fix claimed', icon: CheckCircle2, tone: 'good' },
  quiet: { label: 'Quiet', icon: MoonStar, tone: 'neutral' },
}

const FILTERS = [
  { value: 'all', label: 'All themes' },
  { value: 'persisting', label: 'Persisting' },
  { value: 'new', label: 'New' },
  { value: 'addressed', label: 'Fix claimed' },
  { value: 'quiet', label: 'Quiet' },
] as const

export function GapsView({ slug, onSelect }: GapsViewProps) {
  const { data, isLoading, error } = useTopicGaps(slug)
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['value']>('all')

  // Every sparkline shares one year range and one count scale, so their shapes compare.
  const scale = useMemo(() => {
    const years = data?.themes.flatMap((t) => t.yearly.map((y) => y.year)) ?? []
    const counts = data?.themes.flatMap((t) => t.yearly.map((y) => y.count)) ?? []
    return years.length ? { first: Math.min(...years), last: Math.max(...years), max: Math.max(...counts, 1) } : null
  }, [data])

  if (isLoading) return <Spinner label="Loading open problems…" />
  if (error || !data) return <Notice tone="error" title="The open problems could not be loaded">Check that the API is running.</Notice>
  if (data.themes.length === 0 || !scale) {
    return (
      <Notice title="No open problems yet">
        They appear after the GPU lane has labelled and embedded gap statements:{' '}
        <code>python3 scripts/evolution_full_text.py --gpu-only</code>.
      </Notice>
    )
  }
  const shown = data.themes.filter((t) => filter === 'all' || t.status === filter)
  const counts = Object.fromEntries(FILTERS.map((f) => [f.value, f.value === 'all' ? data.themes.length : data.themes.filter((t) => t.status === f.value).length]))

  return (
    <div className="grid gap-5">
      {/* The edge of the map: open problems sit where the mist begins. */}
      <section className="relative overflow-hidden rounded-xl border border-line bg-surface">
        <div className="mist" aria-hidden="true"><span /><span /><span /><span /></div>
        <div className="relative grid gap-2 p-5 sm:pr-48">
          <h2 className="text-[16px] font-semibold text-fg">
            {counts.new + counts.persisting} open {counts.new + counts.persisting === 1 ? 'problem' : 'problems'} at the edge of this topic
          </h2>
          <p className="max-w-3xl text-[13px] leading-relaxed text-fg-2">
            Limitations that papers state about themselves, or that later papers state about them, grouped by meaning. A theme
            is <b className="font-medium text-fg">persisting</b> when it was first stated before{' '}
            {data.latest_year ? `${data.latest_year - 1}–${data.latest_year}` : 'the last two years'}, is still stated then, and no
            strict link claims a fix. It is <b className="font-medium text-fg">new</b> when it has only been stated in those years. The bars
            count statements per year, with the last two years in the accent.
          </p>
        </div>
        <span className="pointer-events-none absolute right-6 bottom-4 font-myth text-[28px] leading-none text-fg-3 max-sm:hidden" aria-hidden="true">Uncharted</span>
      </section>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            aria-pressed={filter === f.value}
            className={cn(
              'h-7 rounded-full border px-3 text-[12.5px] transition-colors',
              filter === f.value ? 'border-accent-line bg-accent-soft text-fg' : 'border-line text-fg-3 hover:text-fg-2',
            )}
          >
            {f.label} <span className="font-mono tabular-nums">{counts[f.value]}</span>
          </button>
        ))}
      </div>
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {shown.map((t) => (
          <ThemeRow key={t.id} theme={t} scale={scale} latest={data.latest_year} onSelect={onSelect} />
        ))}
      </ul>
    </div>
  )
}

function ThemeRow({ theme, scale, latest, onSelect }: {
  theme: GapTheme
  scale: { first: number; last: number; max: number }
  latest: number | null
  onSelect: (id: string) => void
}) {
  const status = STATUS[theme.status]
  const Icon = status.icon
  return (
    <li className="grid grid-cols-1 gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_220px]">
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone={status.tone}><Icon aria-hidden="true" /> {status.label}</Chip>
          <h4 className="text-[14px] font-medium text-fg">{theme.label}</h4>
          <span className="font-mono text-[12px] text-fg-3 tabular-nums">
            {theme.size} statements · {theme.first_year}–{theme.last_year}
          </span>
        </div>
        {theme.examples.map((e, i) => (
          <blockquote key={i} className="pl-2 border-l-2 border-line text-[12px] text-fg-2 leading-relaxed">
            {e.sentence}
            <span className="block mt-0.5 text-[11px] text-fg-3">
              {e.origin === 'own' ? 'In ' : 'About '}
              <PaperLink paper={e.paper} onSelect={onSelect} />
              {e.origin === 'citing' && e.stated_by && <>, stated by <PaperLink paper={e.stated_by} onSelect={onSelect} /></>}
            </span>
          </blockquote>
        ))}
        {theme.fixed_by.length > 0 && (
          <p className="text-[12px] text-fg-2">
            Fix claimed by {theme.fixed_by.map((p, i) => <span key={p.id}>{i > 0 && ', '}<PaperLink paper={p} onSelect={onSelect} /></span>)}
          </p>
        )}
        {theme.loose_candidates.length > 0 && (
          <p className="text-[12px] text-fg-3">
            Possibly taken on by (loose match, no evidence sentence):{' '}
            {theme.loose_candidates.map((c, i) => (
              <span key={c.paper.id}>{i > 0 && ', '}<PaperLink paper={c.paper} onSelect={onSelect} /> <span className="font-mono tabular-nums">{c.score.toFixed(2)}</span></span>
            ))}
          </p>
        )}
      </div>
      <Sparkline theme={theme} scale={scale} latest={latest} />
    </li>
  )
}

function PaperLink({ paper, onSelect }: { paper: MiniPaper | null; onSelect: (id: string) => void }) {
  if (!paper) return <span>a paper outside the topic</span>
  const name = paper.named_method ?? (paper.title.length > 60 ? `${paper.title.slice(0, 57)}…` : paper.title)
  return (
    <button onClick={() => onSelect(paper.id)} className="text-fg-2 hover:text-accent-ink underline-offset-2 hover:underline">
      {name}{paper.year ? ` (${paper.year})` : ''}
    </button>
  )
}

const BAR_W = 6
const GAP = 2
const H = 40

function Sparkline({ theme, scale, latest }: { theme: GapTheme; scale: { first: number; last: number; max: number }; latest: number | null }) {
  const [hover, setHover] = useState<number | null>(null)
  const byYear = new Map(theme.yearly.map((y) => [y.year, y.count]))
  const years = Array.from({ length: scale.last - scale.first + 1 }, (_, i) => scale.first + i)
  const width = years.length * (BAR_W + GAP) - GAP
  const summary = theme.yearly.map((y) => `${y.year}: ${y.count}`).join(', ')
  const hovered = hover !== null ? { year: hover, count: byYear.get(hover) ?? 0 } : null
  return (
    <figure className="flex flex-col gap-1 self-start">
      <div className="relative">
        <svg width={width} height={H + 1} role="img" aria-label={`Statements per year: ${summary}`} className="overflow-visible">
          {/* SVG colours read the look's CSS variables directly. */}
          <line x1={0} x2={width} y1={H + 0.5} y2={H + 0.5} style={{ stroke: 'var(--line-strong)' }} strokeWidth={1} />
          {years.map((year, i) => {
            const count = byYear.get(year) ?? 0
            const h = count ? Math.max(2, (count / scale.max) * H) : 0
            const recent = latest !== null && year >= latest - 1
            return (
              <g key={year} onMouseEnter={() => setHover(year)} onMouseLeave={() => setHover(null)}>
                {/* Hit target: the full column, wider than the bar. */}
                <rect x={i * (BAR_W + GAP) - GAP / 2} y={0} width={BAR_W + GAP} height={H} fill="transparent" />
                {h > 0 && (
                  <rect
                    x={i * (BAR_W + GAP)}
                    y={H - h}
                    width={BAR_W}
                    height={h}
                    rx={1.5}
                    style={{ fill: recent ? 'var(--accent)' : 'var(--fg-3)' }}
                    opacity={hover === null || hover === year ? 1 : 0.5}
                  />
                )}
              </g>
            )
          })}
        </svg>
        {hovered && (
          <span className="absolute -top-6 left-0 px-1.5 py-0.5 rounded bg-surface border border-line text-[11px] font-mono text-fg tabular-nums whitespace-nowrap pointer-events-none">
            {hovered.year}: {hovered.count} {hovered.count === 1 ? 'statement' : 'statements'}
          </span>
        )}
      </div>
      <figcaption className="flex justify-between text-[10px] font-mono text-fg-3 tabular-nums" style={{ width }}>
        <span>{scale.first}</span>
        <span>{scale.last}</span>
      </figcaption>
    </figure>
  )
}
