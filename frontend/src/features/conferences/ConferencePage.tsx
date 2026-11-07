import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ChevronLeft, ChevronRight, GitBranch, Layers, ScrollText, TrendingDown, TrendingUp, Trophy, X } from 'lucide-react'
import {
  CONF_KINDS, useConfCompare, useConferences, useConfPapers, useConfTrends, useEdition,
  type ConfEdition, type ConfKind, type ConfTerm, type ConfTopic, type ConfVenue,
} from '../../api/queries/conferences'
import { apiErrorMessage } from '../../api/error'
import { ButtonLink } from '../../ui/Button'
import { Card, CardHeader } from '../../ui/Card'
import { EmptyState } from '../../ui/EmptyState'
import { Notice } from '../../ui/Notice'
import { Pager } from '../../ui/Pager'
import { Segmented } from '../../ui/Segmented'
import { SkeletonRows } from '../../ui/Skeleton'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { ConfPaperPanel } from './ConfPaperPanel'
import { MAX_SERIES, SERIES_COLORS, pct, useWidth } from './format'
import { KindsToggle, PaperRow, TopicShares } from './parts'
import { TrendChart } from './TrendChart'

type View = 'overview' | 'trends' | 'compare'
const VIEWS: { value: View; label: string }[] = [
  { value: 'overview', label: 'Overview' }, { value: 'trends', label: 'Trends' }, { value: 'compare', label: 'Compare' },
]
const ALL_KINDS = CONF_KINDS.map((k) => k.value)
const PAGE = 20
const MAX_PAGES = 10

const selectClass = 'h-7 rounded-lg border border-line bg-surface-2 px-2 font-mono text-[12.5px] text-fg focus:border-accent-line focus:outline-none'

/** One venue (or the whole family) of the ACL Anthology: an edition's topics, terms, awards and top papers; topics
 * over the years; venues side by side. Year, kinds, view and topic live in the address, so a page can be shared. */
export function ConferencePage() {
  const { venue = 'all' } = useParams<{ venue: string }>()
  const [params, setParams] = useSearchParams()
  const year = params.get('year') ? Number(params.get('year')) : null
  const view = (VIEWS.some((v) => v.value === params.get('view')) ? params.get('view') : 'overview') as View
  const topic = params.get('topic') ? Number(params.get('topic')) : null
  const kinds = (params.get('kinds')?.split(',').filter((k): k is ConfKind => ALL_KINDS.includes(k as ConfKind)) ?? [])
  const picked = kinds.length ? kinds : ALL_KINDS
  const [paper, setPaper] = useState<string | null>(null)

  const set = (changes: Record<string, string | number | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === '') next.delete(k)
      else next.set(k, String(v))
    }
    setParams(next, { replace: true })
  }

  const list = useConferences()
  const edition = useEdition(venue, year, picked)
  const info = list.data?.venues.find((v) => v.slug === venue)
  const name = venue === 'all' ? (list.data?.family.name ?? 'ACL family') : (info?.name ?? venue.toUpperCase())
  const e = edition.data
  const years = e?.years.map((y) => y.year) ?? []
  const at = e ? years.indexOf(e.year) : -1

  return (
    <div className="mx-auto max-w-[1100px]">
      <Link to="/library/conferences" className="mb-3 inline-flex items-center gap-1.5 text-[12.5px] text-fg-3 hover:text-fg">
        <ArrowLeft className="h-3.5 w-3.5" /> Conferences
      </Link>
      <header className="flex flex-wrap items-end justify-between gap-4 pb-5">
        <div className="grid gap-1">
          <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-fg">
            {name}{view === 'overview' && e ? <span className="font-mono text-fg-2"> {e.year}</span> : null}
          </h1>
          <p className="text-fg-2">{venue === 'all' ? 'ACL, EMNLP, NAACL, EACL, AACL, COLING, TACL and CL together' : info?.full_name}</p>
        </div>
        <Segmented label="View" value={view} options={VIEWS} onChange={(v) => set({ view: v === 'overview' ? null : v })} />
      </header>

      <div className="mb-5 flex flex-wrap items-center gap-3">
        {view === 'overview' && e && (
          <div className="flex items-center gap-1" role="group" aria-label="Edition">
            <button type="button" className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-fg-2 hover:bg-surface-2 hover:text-fg disabled:opacity-40"
              disabled={at <= 0} onClick={() => set({ year: years[at - 1] })} aria-label="Previous edition"><ChevronLeft className="h-4 w-4" /></button>
            <select aria-label="Year" className={selectClass} value={e.year} onChange={(ev) => set({ year: Number(ev.target.value) })}>
              {[...years].reverse().map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <button type="button" className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-fg-2 hover:bg-surface-2 hover:text-fg disabled:opacity-40"
              disabled={at < 0 || at >= years.length - 1} onClick={() => set({ year: years[at + 1] })} aria-label="Next edition"><ChevronRight className="h-4 w-4" /></button>
          </div>
        )}
        <KindsToggle value={picked} onChange={(k) => set({ kinds: k.length === ALL_KINDS.length ? null : k.join(',') })}
          available={venue === 'tacl' || venue === 'cl' ? ['journal'] : venue === 'all' ? undefined : ['main', 'findings']} />
        {edition.isFetching && !edition.isLoading && <Spinner className="h-3.5 w-3.5" />}
      </div>

      {edition.isLoading && <SkeletonRows count={6} />}
      {edition.error && (
        <EmptyState icon={Layers} title={`No ${name} papers to show`}>
          {apiErrorMessage(edition.error, 'The conference did not load.')} Try other kinds of papers above.
        </EmptyState>
      )}
      {e && view === 'overview' && (
        <Overview edition={e} venue={venue} topic={topic} kinds={picked} onTopic={(t) => set({ topic: t })} onPaper={setPaper} />
      )}
      {e && view === 'trends' && list.data && (
        <TrendsView venue={venue} name={name} kinds={picked} topics={list.data.topics}
          onTopic={(t) => set({ view: null, topic: t })} />
      )}
      {e && view === 'compare' && list.data && (
        <CompareView venue={venue} year={e.year} kinds={picked} venues={list.data.venues} onYear={(y) => set({ year: y })} />
      )}
      {paper && <ConfPaperPanel paperId={paper} onClose={() => setPaper(null)} onOpen={setPaper} />}
    </div>
  )
}

// ── overview ─────────────────────────────────────────────────────────

function Overview({ edition: e, venue, topic, kinds, onTopic, onPaper }: {
  edition: ConfEdition
  venue: string
  topic: number | null
  kinds: ConfKind[]
  onTopic: (id: number | null) => void
  onPaper: (id: string) => void
}) {
  const papersRef = useRef<HTMLDivElement>(null)
  const prev = e.previous_year ? e.years.find((y) => y.year === e.previous_year)?.papers : null
  const sorting = e.progress.sorted < e.progress.papers
  const pick = (id: number) => {
    onTopic(id === topic ? null : id)
    if (id !== topic) setTimeout(() => papersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  return (
    <div className="grid gap-4">
      {sorting && (
        <Notice title="Still sorting this edition's papers">
          {e.progress.sorted.toLocaleString()} of {e.progress.papers.toLocaleString()} papers are sorted into topics;
          the shares below count those.
        </Notice>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader icon={ScrollText} title={`${e.name} ${e.year} in brief`} />
            <div className="px-4 pb-4">
              {e.summary
                ? <p className="text-[14px] leading-relaxed text-fg-2">{e.summary.text}</p>
                : <p className="text-[13px] text-fg-3">The summary is written once this edition's papers are sorted into topics.</p>}
            </div>
          </Card>
          <Card>
            <CardHeader icon={Layers} title="Topics"
              action={<span className="text-[11.5px] text-fg-3">share · papers · change{e.previous_year ? ` since ${e.previous_year}` : ''} (pts)</span>} />
            <TopicShares topics={e.topics} onPick={pick} picked={topic} limit={12} />
          </Card>
        </div>
        <div className="grid content-start gap-4">
          <Card className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3.5">
            <Stat label="Papers" value={e.papers.toLocaleString()}
              hint={prev ? `${e.papers >= prev ? '+' : '−'}${Math.abs(e.papers - prev).toLocaleString()} since ${e.previous_year}` : 'First edition'} />
            <Stat label="Award winners" value={String(e.awards.length)} />
            {Object.entries(e.by_kind).map(([k, n]) => (
              <Stat key={k} label={CONF_KINDS.find((c) => c.value === k)?.label ?? k} value={(n ?? 0).toLocaleString()} />
            ))}
          </Card>
          <TermsCard title="Rising terms" icon={TrendingUp} terms={e.terms.rising.slice(0, 14)} since={e.previous_year} />
          <TermsCard title="Falling terms" icon={TrendingDown} terms={e.terms.falling.slice(0, 8)} since={e.previous_year} />
        </div>
      </div>
      {e.awards.length > 0 && <Awards edition={e} onPaper={onPaper} />}
      <div ref={papersRef} className="scroll-mt-4">
        <TopPapers key={`${venue}:${e.year}:${topic}:${kinds.join()}`} venue={venue} year={e.year} topic={topic} topicName={e.topics.find((t) => t.id === topic)?.name ?? null}
          kinds={kinds} onClear={() => onTopic(null)} onPaper={onPaper} />
      </div>
    </div>
  )
}

const AWARDS_SHOWN = 6

function Awards({ edition: e, onPaper }: { edition: ConfEdition; onPaper: (id: string) => void }) {
  const [all, setAll] = useState(false)
  const shown = all ? e.awards : e.awards.slice(0, AWARDS_SHOWN)
  return (
    <Card>
      <CardHeader icon={Trophy} title="Award-winning papers" action={<span className="text-[11.5px] text-fg-3">best papers first</span>} />
      <ul>{shown.map((p) => <PaperRow key={p.id} paper={p} onOpen={onPaper} />)}</ul>
      {e.awards.length > AWARDS_SHOWN && (
        <button type="button" onClick={() => setAll(!all)} className="w-full border-t border-line px-4 py-2 text-left text-[12.5px] text-fg-2 hover:text-fg">
          {all ? 'Fewer' : `All ${e.awards.length} award winners`}
        </button>
      )}
    </Card>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-[11.5px] text-fg-3">{label}</p>
      <p className="text-[17px] font-semibold text-fg">{value}</p>
      {hint && <p className="text-[11.5px] text-fg-3">{hint}</p>}
    </div>
  )
}

function TermsCard({ title, icon, terms, since }: { title: string; icon: typeof TrendingUp; terms: ConfTerm[]; since: number | null }) {
  return (
    <Card>
      <CardHeader icon={icon} title={title} action={since ? <span className="text-[11.5px] text-fg-3">papers using it, {since} → now</span> : undefined} />
      {terms.length ? (
        <ul className="grid gap-0.5 px-4 pb-3">
          {terms.map((t) => (
            <li key={t.term} className="flex items-baseline justify-between gap-3 text-[13px]">
              <span className="truncate text-fg">{t.term}</span>
              <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-fg-3">{pct(t.prev_share)} → <span className="text-fg-2">{pct(t.share)}</span></span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 pb-3 text-[12.5px] text-fg-3">{since ? 'Too few papers to tell.' : 'No earlier edition to compare with.'}</p>
      )}
    </Card>
  )
}

function TopPapers({ venue, year, topic, topicName, kinds, onClear, onPaper }: {
  venue: string
  year: number
  topic: number | null
  topicName: string | null
  kinds: ConfKind[]
  onClear: () => void
  onPaper: (id: string) => void
}) {
  const [scope, setScope] = useState<'year' | 'all'>('year')
  const [page, setPage] = useState(1)  // the parent keys this card by venue, year, topic and kinds: page 1 again
  const { data, isLoading, isFetching } = useConfPapers(venue, {
    year: scope === 'year' ? year : null, topic, kinds, offset: (page - 1) * PAGE, limit: PAGE,
  })
  const pages = Math.min(MAX_PAGES, Math.ceil((data?.total ?? 0) / PAGE))
  return (
    <Card>
      <CardHeader icon={Trophy}
        title={<span className="flex items-center gap-2">Top papers{topicName && <>: {topicName}
          <button type="button" onClick={onClear} aria-label="All topics" className="rounded p-0.5 text-fg-3 hover:bg-surface-2 hover:text-fg"><X className="h-3.5 w-3.5" /></button></>}</span>}
        action={
          <div className="flex items-center gap-2">
            {topicName && (
              <ButtonLink to={`/evolution?q=${encodeURIComponent(topicName)}`} variant="ghost" size="sm" title="Find or build a research map of this topic">
                <GitBranch /> Map it
              </ButtonLink>
            )}
            <Segmented label="Which years" value={scope} onChange={(s) => { setScope(s); setPage(1) }}
              options={[{ value: 'year', label: String(year) }, { value: 'all', label: 'All years' }]} />
          </div>
        } />
      <p className="px-4 pb-2 text-[12px] text-fg-3">
        Award winners first, then by citations{topicName ? '' : '. Pick a topic above to see its own'}.
        {data ? ` ${data.total.toLocaleString()} papers.` : ''}
      </p>
      {isLoading ? <div className="px-4 pb-4"><SkeletonRows count={4} /></div> : data && data.papers.length ? (
        <ul className={cn('border-t border-line transition-opacity', isFetching && 'opacity-60')}>
          {data.papers.map((p, i) => <PaperRow key={p.id} paper={p} onOpen={onPaper} rank={(page - 1) * PAGE + i + 1} />)}
        </ul>
      ) : <p className="px-4 pb-4 text-[13px] text-fg-3">No papers.</p>}
      <Pager page={page} pages={pages} onChange={setPage} label="Top papers pages" className="justify-center border-t border-line py-2" />
    </Card>
  )
}

// ── trends ───────────────────────────────────────────────────────────

const STARTS = [{ value: '2000', label: 'Since 2000' }, { value: '2015', label: 'Since 2015' }, { value: 'all', label: 'All years' }] as const
type Start = (typeof STARTS)[number]['value']

/** Picked topics keep their colour slot until they are dropped; a new one takes the first free slot. */
function useSlots() {
  const [slots, setSlots] = useState<(number | null)[]>(Array(MAX_SERIES).fill(null))
  const toggle = (id: number) => setSlots((s) => {
    if (s.includes(id)) return s.map((x) => (x === id ? null : x))
    const free = s.indexOf(null)
    if (free < 0) return s
    const next = [...s]
    next[free] = id
    return next
  })
  return { slots, setSlots, toggle }
}

function TrendsView({ venue, name, kinds, topics, onTopic }: {
  venue: string
  name: string
  kinds: ConfKind[]
  topics: ConfTopic[]
  onTopic: (id: number) => void
}) {
  const { data, isLoading } = useConfTrends(venue, kinds)
  const [start, setStart] = useState<Start>('2000')
  const { slots, setSlots, toggle } = useSlots()

  const years = useMemo(() => (data?.years ?? []).filter((y) => y.sorted > 0 && (start === 'all' || y.year >= Number(start))), [data, start])
  const share = (y: (typeof years)[number], id: number) => (y.topics[String(id)] ?? 0) / y.sorted

  // The five biggest topics of the latest year, the first time there is data.
  useEffect(() => {
    if (!years.length || slots.some((s) => s !== null)) return
    const last = years[years.length - 1]
    const top = topics.map((t) => t.id).sort((a, b) => share(last, b) - share(last, a)).slice(0, 5)
    setSlots([...top, ...Array(MAX_SERIES - top.length).fill(null)])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [years.length])

  // Over the years shown: the topics whose share grew and shrank most, first edition against last.
  const movers = useMemo(() => {
    if (years.length < 2) return []
    const [first, last] = [years[0], years[years.length - 1]]
    return topics.map((t) => ({ t, change: share(last, t.id) - share(first, t.id) })).sort((a, b) => b.change - a.change)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [years, topics])

  if (isLoading) return <SkeletonRows count={6} />
  if (years.length < 2) {
    return (
      <EmptyState icon={TrendingUp} title="Not enough years sorted yet">
        Topics over the years show once two years of {name}'s papers are sorted into topics. They are sorted newest
        first{years.length ? `; ${years[0].year} is done so far` : ''}.
      </EmptyState>
    )
  }
  const byId = new Map(topics.map((t) => [t.id, t]))
  const series = slots.flatMap((id, slot) => (id === null || !byId.has(id) ? [] : [{
    id: String(id), name: byId.get(id)!.name, color: SERIES_COLORS[slot],
    values: years.map((y) => share(y, id)),
  }]))
  const full = slots.every((s) => s !== null)

  return (
    <div className="grid gap-4">
      <Card className="grid gap-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[13px] font-medium text-fg">Share of {name}'s papers per topic</h2>
          <Segmented label="Years" value={start} options={[...STARTS]} onChange={setStart} />
        </div>
        {series.length
          ? <TrendChart years={years.map((y) => y.year)} series={series} label={`Share of ${name}'s papers per topic, ${years[0].year} to ${years[years.length - 1].year}`} />
          : <p className="py-10 text-center text-[13px] text-fg-3">Pick topics below to draw them.</p>}
        {start !== '2015' && years[0].year < 2015 && (
          <p className="text-[11.5px] text-fg-3">Before about 2015 most papers have only a title (or an abstract from OpenAlex or Semantic Scholar), so their topics are less certain.</p>
        )}
      </Card>
      <Card>
        <CardHeader icon={Layers} title="Topics to draw" action={<span className="text-[11.5px] text-fg-3">up to {MAX_SERIES} at once</span>} />
        <div className="flex flex-wrap gap-1.5 px-4 pb-4">
          {topics.map((t) => {
            const slot = slots.indexOf(t.id)
            return (
              <button key={t.id} type="button" aria-pressed={slot >= 0} disabled={slot < 0 && full} onClick={() => toggle(t.id)}
                className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] transition-colors disabled:opacity-40',
                  slot >= 0 ? 'border-line-strong bg-surface-2 text-fg' : 'border-line text-fg-2 hover:text-fg')}>
                {slot >= 0 && <span className="h-2 w-2 rounded-full" style={{ background: SERIES_COLORS[slot] }} aria-hidden="true" />}
                {t.name}
              </button>
            )
          })}
        </div>
      </Card>
      {movers.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          <MoversCard title={`Grew most, ${years[0].year}–${years[years.length - 1].year}`} icon={TrendingUp} rows={movers.slice(0, 6)} onTopic={onTopic} />
          <MoversCard title={`Shrank most, ${years[0].year}–${years[years.length - 1].year}`} icon={TrendingDown} rows={movers.slice(-6).reverse()} onTopic={onTopic} />
        </div>
      )}
    </div>
  )
}

function MoversCard({ title, icon, rows, onTopic }: { title: string; icon: typeof TrendingUp; rows: { t: ConfTopic; change: number }[]; onTopic: (id: number) => void }) {
  return (
    <Card>
      <CardHeader icon={icon} title={title} />
      <ul className="grid px-2 pb-2">
        {rows.map(({ t, change }) => (
          <li key={t.id}>
            <button type="button" onClick={() => onTopic(t.id)} className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-1 text-left text-[13px] hover:bg-surface-2">
              <span className="truncate text-fg">{t.name}</span>
              <span className="shrink-0 font-mono text-[12px] tabular-nums text-fg-2">{change >= 0 ? '+' : '−'}{Math.abs(change * 100).toFixed(1)} pts</span>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ── compare ──────────────────────────────────────────────────────────

function CompareView({ venue, year, kinds, venues, onYear }: {
  venue: string
  year: number
  kinds: ConfKind[]
  venues: ConfVenue[]
  onYear: (year: number) => void
}) {
  const withPapers = venues.filter((v) => v.papers > 0)
  const [picked, setPicked] = useState<string[]>(() => {
    const held = withPapers.filter((v) => v.years.includes(year)).map((v) => v.slug)
    const first = venue !== 'all' ? [venue] : []
    return [...new Set([...first, ...held])].slice(0, 4)
  })
  const { data, isLoading, isFetching } = useConfCompare(picked, year, kinds)
  const [ref, width] = useWidth<HTMLDivElement>()
  const yearsOf = [...new Set(withPapers.filter((v) => picked.includes(v.slug)).flatMap((v) => v.years))].sort((a, b) => b - a)

  const rows = useMemo(() => {
    if (!data) return []
    // A venue none of whose papers are sorted yet has no shares, not shares of nought.
    const shares = (v: (typeof data.venues)[number], id: number) => (v.sorted ? (v.topics[String(id)] ?? 0) / v.sorted : null)
    const sum = (xs: (number | null)[]) => xs.reduce<number>((s, x) => s + (x ?? 0), 0)
    return data.topics.map((t) => ({ t, values: data.venues.map((v) => shares(v, t.id)) }))
      .filter((r) => r.values.some((x) => x !== null && x > 0))
      .sort((a, b) => sum(b.values) - sum(a.values))
  }, [data])
  const top = Math.max(0.0001, ...rows.flatMap((r) => r.values.map((v) => v ?? 0)))

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] text-fg-3">Venues</span>
        {withPapers.map((v) => {
          const on = picked.includes(v.slug)
          return (
            <button key={v.slug} type="button" aria-pressed={on} disabled={!on && picked.length >= 6}
              onClick={() => setPicked(on ? picked.filter((p) => p !== v.slug) : [...picked, v.slug])}
              className={cn('rounded-full border px-2.5 py-0.5 text-[12px] transition-colors disabled:opacity-40',
                on ? 'border-line-strong bg-surface-2 text-fg' : 'border-line text-fg-2 hover:text-fg',
                !v.years.includes(year) && !on && 'opacity-60')}
              title={v.years.includes(year) ? undefined : `No ${year} edition`}>
              {v.name}
            </button>
          )
        })}
        <select aria-label="Year to compare" className={cn(selectClass, 'ml-auto')} value={year} onChange={(e) => onYear(Number(e.target.value))}>
          {yearsOf.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      {!picked.length ? <EmptyState icon={Layers} title="Pick venues to compare" /> : isLoading ? <SkeletonRows count={8} /> : data && (
        <Card className={cn('transition-opacity', isFetching && 'opacity-60')}>
          <CardHeader icon={Layers} title={`Topic shares, ${year}`}
            action={data.missing.length ? <span className="text-[11.5px] text-fg-3">No {year} edition: {data.missing.map((m) => withPapers.find((v) => v.slug === m)?.name ?? m).join(', ')}</span> : undefined} />
          <div ref={ref} className="overflow-x-auto px-2 pb-2">
            <table className="w-full min-w-[520px] text-[12.5px]">
              <caption className="sr-only">Share of each venue's {year} papers per topic</caption>
              <thead>
                <tr className="text-left text-fg-3">
                  <th scope="col" className="px-2 py-1.5 font-normal">Topic</th>
                  {data.venues.map((v) => (
                    <th key={v.venue} scope="col" className="px-2 py-1.5 font-normal">
                      <span className="text-fg">{v.name}</span> <span className="font-mono">{v.papers.toLocaleString()}</span>
                      {v.sorted < v.papers && <span className="block text-[11px]">{v.sorted ? `${Math.round((v.sorted / v.papers) * 100)}% sorted` : 'not sorted yet'}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(({ t, values }) => {
                  const best = Math.max(...values.map((v) => v ?? 0))
                  return (
                    <tr key={t.id} className="border-t border-line">
                      <th scope="row" className="max-w-[14rem] truncate px-2 py-1.5 text-left font-normal text-fg" title={t.name}>{t.name}</th>
                      {values.map((v, i) => v === null ? (
                        <td key={data.venues[i].venue} className="px-2 py-1.5 text-fg-3">–</td>
                      ) : (
                        <td key={data.venues[i].venue} className="px-2 py-1.5">
                          <div className="flex items-center gap-2">
                            <span className="relative h-2 flex-1 rounded-full" style={{ maxWidth: width > 700 ? 140 : 80 }} aria-hidden="true">
                              <span className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: v ? `max(3px, ${(v / top) * 100}%)` : 0 }} />
                            </span>
                            <span className={cn('w-12 text-right font-mono tabular-nums', v === best && values.length > 1 ? 'text-fg' : 'text-fg-2')}>{pct(v)}</span>
                          </div>
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
