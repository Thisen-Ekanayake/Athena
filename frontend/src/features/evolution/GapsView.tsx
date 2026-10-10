import { useMemo, useState } from 'react'
import { CheckCircle2, CircleDot, Loader2, MoonStar } from 'lucide-react'
import { Alert } from '../../components/shared/Alert'
import { useTopicGaps, type GapTheme, type MiniPaper } from './api'

interface GapsViewProps {
  slug: string
  onSelect: (id: string) => void
}

const STATUS = {
  persisting: { label: 'Persisting', icon: CircleDot, className: 'text-accent-warning border-accent-warning/40' },
  addressed: { label: 'Fix claimed', icon: CheckCircle2, className: 'text-accent-success border-accent-success/40' },
  quiet: { label: 'Quiet', icon: MoonStar, className: 'text-text-muted border-border-subtle' },
} as const

const FILTERS = [
  { value: 'all', label: 'All themes' },
  { value: 'persisting', label: 'Persisting' },
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

  if (isLoading) return <p className="flex items-center gap-2 text-sm text-text-muted"><Loader2 className="w-4 h-4 animate-spin" /> Loading gaps…</p>
  if (error || !data) return <Alert type="error" title="Could not load the gaps">Check that the API is running.</Alert>
  if (data.themes.length === 0 || !scale) {
    return (
      <Alert type="info" title="No gap themes yet">
        Gap themes appear after the GPU lane has labelled and embedded gap statements:{' '}
        <code>python3 scripts/evolution_full_text.py --gpu-only</code>.
      </Alert>
    )
  }
  const shown = data.themes.filter((t) => filter === 'all' || t.status === filter)
  const counts = Object.fromEntries(FILTERS.map((f) => [f.value, f.value === 'all' ? data.themes.length : data.themes.filter((t) => t.status === f.value).length]))

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-text-secondary max-w-3xl">
        Limitations papers state about themselves, and that later papers state about them, grouped by meaning. A theme
        is <b className="font-semibold text-text-primary">persisting</b> when it was still stated in {data.latest_year ? `${data.latest_year - 1}–${data.latest_year}` : 'the last two years'} and no
        strict link claims a fix. The bars count statements per year; the last two years are highlighted.
      </p>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter themes by status">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            aria-pressed={filter === f.value}
            className={`px-3 py-1 rounded-full border text-[12px] transition-colors ${
              filter === f.value ? 'border-accent-primary/60 bg-accent-primary/15 text-text-primary' : 'border-border-subtle text-text-muted hover:text-text-secondary'
            }`}
          >
            {f.label} <span className="font-mono tabular-nums">{counts[f.value]}</span>
          </button>
        ))}
      </div>
      <ul className="flex flex-col divide-y divide-border-subtle">
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
    <li className="py-4 grid grid-cols-1 lg:grid-cols-[1fr_220px] gap-4">
      <div className="flex flex-col gap-2 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium ${status.className}`}>
            <Icon className="w-3 h-3" aria-hidden="true" /> {status.label}
          </span>
          <h4 className="text-[14px] font-semibold text-text-primary">{theme.label}</h4>
          <span className="text-[12px] font-mono text-text-muted tabular-nums">
            {theme.size} statements · {theme.first_year}–{theme.last_year}
          </span>
        </div>
        {theme.examples.map((e, i) => (
          <blockquote key={i} className="pl-2 border-l-2 border-border-subtle text-[12px] text-text-secondary leading-relaxed">
            {e.sentence}
            <span className="block mt-0.5 text-[11px] text-text-muted">
              {e.origin === 'own' ? 'In ' : 'About '}
              <PaperLink paper={e.paper} onSelect={onSelect} />
              {e.origin === 'citing' && e.stated_by && <>, stated by <PaperLink paper={e.stated_by} onSelect={onSelect} /></>}
            </span>
          </blockquote>
        ))}
        {theme.fixed_by.length > 0 && (
          <p className="text-[12px] text-text-secondary">
            Fix claimed by {theme.fixed_by.map((p, i) => <span key={p.id}>{i > 0 && ', '}<PaperLink paper={p} onSelect={onSelect} /></span>)}
          </p>
        )}
        {theme.loose_candidates.length > 0 && (
          <p className="text-[12px] text-text-muted">
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
    <button onClick={() => onSelect(paper.id)} className="text-text-secondary hover:text-accent-primary underline-offset-2 hover:underline">
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
          {/* Colours from the theme's CSS variables: they are not Tailwind colour tokens. */}
          <line x1={0} x2={width} y1={H + 0.5} y2={H + 0.5} style={{ stroke: 'var(--border-default)' }} strokeWidth={1} />
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
                    style={{ fill: recent ? 'var(--color-accent-primary)' : 'var(--text-muted)' }}
                    opacity={hover === null || hover === year ? 1 : 0.5}
                  />
                )}
              </g>
            )
          })}
        </svg>
        {hovered && (
          <span className="absolute -top-6 left-0 px-1.5 py-0.5 rounded bg-glass-fill border border-border-subtle text-[11px] font-mono text-text-primary tabular-nums whitespace-nowrap pointer-events-none">
            {hovered.year}: {hovered.count} {hovered.count === 1 ? 'statement' : 'statements'}
          </span>
        )}
      </div>
      <figcaption className="flex justify-between text-[10px] font-mono text-text-muted tabular-nums" style={{ width }}>
        <span>{scale.first}</span>
        <span>{scale.last}</span>
      </figcaption>
    </figure>
  )
}
