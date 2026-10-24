import { Suspense, lazy, useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent, type MouseEvent, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, GitBranch, Lightbulb, Maximize2, Minimize2, RefreshCw, Search, Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { timeAgo } from '../../components/items/format'
import { useIsAdmin } from '../../api/queries/auth'
import { Button, ButtonLink } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { EmptyState } from '../../ui/EmptyState'
import { InfoTip } from '../../ui/InfoTip'
import { Notice } from '../../ui/Notice'
import { PageHeader } from '../../ui/PageHeader'
import { Segmented } from '../../ui/Segmented'
import { Skeleton } from '../../ui/Skeleton'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { EvolutionGraph } from './EvolutionGraph'
import { GapsView } from './GapsView'
import { MapPaperPanel } from './MapPaperPanel'
import { ExportMenu } from './ExportMenu'
import { FollowButton } from '../inbox/FollowButton'
import type { GraphExporter } from './graphExport'
import { NewInMaps } from './NewInMaps'
import { ProposalPanel } from './ProposalPanel'
import { ShareMenu } from './ShareMenu'
import { WriteReviewButton } from '../reviews/WriteReviewButton'
import { TimelineStrip } from './TimelineStrip'
import {
  createProposal,
  isBuilding,
  isBusy,
  searchTopics,
  useDeleteTopic,
  useMapScope,
  useEvolutionTopics,
  useRebuildTopic,
  useTopicGraph,
  useTopicStatus,
  useTopicTimeline,
  type EvolutionNode,
  type EvolutionTopic,
  type TopicProposal,
  type TopicSearchResult,
  type TopicStatus,
} from './api'

// The tabs beyond the map load when first opened, so the map's own chunk stays small.
const AskMap = lazy(() => import('./AskMap').then((m) => ({ default: m.AskMap })))
const ChangesView = lazy(() => import('./ChangesView').then((m) => ({ default: m.ChangesView })))
const LinksView = lazy(() => import('./LinksView').then((m) => ({ default: m.LinksView })))
const PeopleView = lazy(() => import('./PeopleView').then((m) => ({ default: m.PeopleView })))
const ReadingPath = lazy(() => import('./ReadingPath').then((m) => ({ default: m.ReadingPath })))

const LIMITS = [
  { value: '80', label: '80' },
  { value: '250', label: '250' },
  { value: '600', label: '600' },
  { value: '0', label: 'All' }, // 0 asks the API for every paper in the map
]

/**
 * Shows an element full screen. Without the Fullscreen API (Safari on iPhone) it fills the window
 * instead, and Escape leaves.
 */
function useFullScreen<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [on, setOn] = useState(false)
  useEffect(() => {
    const sync = () => {
      if (!document.fullscreenElement) setOn(false)
    }
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])
  useEffect(() => {
    if (!on) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOn(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [on])
  const toggle = () => {
    if (on) {
      if (document.fullscreenElement) void document.exitFullscreen()
      setOn(false)
      return
    }
    setOn(true)
    if (document.fullscreenEnabled) ref.current?.requestFullscreen().catch(() => {})
  }
  return { ref, on, toggle }
}

type Tab = 'map' | 'path' | 'gaps' | 'ask' | 'people' | 'links' | 'changes' | 'no-full-text'
const TABS: { id: Tab; label: string }[] = [
  { id: 'map', label: 'Lineage map' },
  { id: 'path', label: 'Reading path' },
  { id: 'gaps', label: 'Open problems' },
  { id: 'ask', label: 'Ask' },
  { id: 'people', label: 'People' },
  { id: 'links', label: 'Links' },
  { id: 'changes', label: 'Changes' },
]
const TAB_IDS = new Set<string>([...TABS.map((t) => t.id), 'no-full-text'])
// A shared link leaves out what needs an account (questions cost model time) and other maps it can't open.
const SHARED_TABS = new Set<Tab>(['map', 'path', 'gaps', 'people', 'changes', 'no-full-text'])

/** How a field developed: its lineage of papers, its milestones and the problems still open. */
export function EvolutionPage() {
  const { slug } = useParams<{ slug: string }>()
  return (
    <div className="mx-auto max-w-[1400px]">
      {slug ? (
        <TopicView key={slug} slug={slug} />
      ) : (
        <>
          <PageHeader
            title="Evolution"
            description="How a field developed: which papers it grew from, its milestones, and the problems still open."
            actions={<ButtonLink to="/evolution/ideas" variant="ai" size="sm"><Lightbulb /> Check an idea</ButtonLink>}
          />
          <TopicSearch />
          <div className="grid gap-8">
            <NewInMaps />
            <TopicList />
          </div>
        </>
      )}
    </div>
  )
}

const STATUS_LABEL: Record<TopicStatus, string> = {
  pending: 'queued',
  building: 'building',
  refining: 'refining',
  ready: 'ready',
  failed: 'failed',
}

/** Finds the map for a query, or proposes one to build. ?q= (from ⌘K) runs a search on arrival. */
function TopicSearch() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') ?? '')
  const [pending, setPending] = useState(false)
  const [result, setResult] = useState<TopicSearchResult | null>(null)
  const [proposal, setProposal] = useState<TopicProposal | null>(null)
  const [error, setError] = useState<string | null>(null)

  const propose = useCallback(async (q: string) => {
    setPending(true)
    setError(null)
    try {
      setProposal(await createProposal(q))
    } catch (e) {
      setError(apiErrorMessage(e, 'The proposal failed. Check that the API is running and try again.'))
    } finally {
      setPending(false)
    }
  }, [])

  const run = useCallback(async (raw: string) => {
    const q = raw.trim()
    if (!q) return
    setPending(true)
    setError(null)
    setResult(null)
    setProposal(null)
    try {
      const found = await searchTopics(q)
      if (found.found && found.match.method === 'alias') {
        navigate(`/evolution/${found.topic.slug}`)
        return
      }
      setResult(found)
      if (!found.found) await propose(q)
    } catch (e) {
      setError(apiErrorMessage(e, 'The search failed. Check that the API is running and try again.'))
    } finally {
      setPending(false)
    }
  }, [navigate, propose])

  // A query handed over from ⌘K: search once, then drop it from the URL.
  const handedOver = useRef(false)
  useEffect(() => {
    const q = params.get('q')
    if (q && !handedOver.current) {
      handedOver.current = true
      setParams({}, { replace: true })
      void run(q)
    }
  }, [params, setParams, run])

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void run(query)
  }

  return (
    <div className="mb-6 grid gap-3">
      <form onSubmit={onSubmit} className="flex max-w-2xl gap-2">
        <label className="flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-lg border border-line bg-surface px-3 focus-within:border-accent-line">
          <Search className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
          <input
            id="evolution-topic-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Any research topic, e.g. object tracking or mixture of experts"
            maxLength={200}
            aria-label="Topic"
            className="min-w-0 flex-1 bg-transparent text-[13.5px] text-fg placeholder:text-fg-3 focus:outline-none"
          />
        </label>
        <Button type="submit" variant="primary" className="h-9" disabled={pending || !query.trim()}>
          {pending ? <Spinner className="h-4 w-4" /> : 'Show evolution'}
        </Button>
      </form>
      {error && <Notice tone="error" title="Something went wrong" className="max-w-2xl">{error}</Notice>}
      {result?.found && !proposal && (
        <div className="flex max-w-2xl flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-surface px-4 py-3 text-[13px]">
          <span className="min-w-0 flex-1 text-fg-2">
            The closest map is <span className="text-fg">{result.topic.name}</span>, whose papers match “{result.query}”.
          </span>
          <ButtonLink to={`/evolution/${result.topic.slug}`} variant="secondary" size="sm">Open it</ButtonLink>
          <Button variant="ghost" size="sm" onClick={() => void propose(result.query)} disabled={pending}>
            Propose a map for “{result.query}”
          </Button>
        </div>
      )}
      {pending && !result && <Spinner label="Looking for papers in OpenAlex…" />}
      {proposal && <ProposalPanel key={proposal.id} proposal={proposal} onCancel={() => { setProposal(null); setResult(null) }} />}
    </div>
  )
}

function TopicList() {
  const { data: topics, isLoading, error } = useEvolutionTopics()
  if (isLoading) {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        {[0, 1].map((i) => <Skeleton key={i} className="h-32 rounded-xl" />)}
      </div>
    )
  }
  if (error) return <Notice tone="error" title="Topics could not be loaded">Check that the API is running.</Notice>
  const curated = (topics ?? []).filter((t) => t.origin !== 'search')
  const searched = (topics ?? []).filter((t) => t.origin === 'search')
  if (!curated.length && !searched.length) {
    return (
      <EmptyState icon={GitBranch} title="No research maps yet">
        Search for a topic above to build one, or seed the curated maps with <code className="font-mono text-[12px]">python3 scripts/seed_evolution_topics.py</code>.
      </EmptyState>
    )
  }
  return (
    <div className="grid gap-6">
      {searched.length > 0 && (
        <section className="grid gap-2.5">
          <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Your maps</h2>
          <div className="grid gap-3 md:grid-cols-2">{searched.map((t) => <TopicCard key={t.slug} topic={t} />)}</div>
        </section>
      )}
      {curated.length > 0 && (
        <section className="grid gap-2.5">
          <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Curated maps</h2>
          <div className="grid gap-3 md:grid-cols-2">{curated.map((t) => <TopicCard key={t.slug} topic={t} />)}</div>
        </section>
      )}
    </div>
  )
}

function TopicCard({ topic: t }: { topic: EvolutionTopic }) {
  const remove = useDeleteTopic()
  const isAdmin = useIsAdmin()
  const onDelete = (e: MouseEvent) => {
    e.preventDefault()
    if (window.confirm(`Delete the map for “${t.name}”? Its papers stay available to other maps.`)) remove.mutate(t.slug)
  }
  return (
    <Link to={`/evolution/${t.slug}`} className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2/50">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] font-medium text-fg">{t.name}</h3>
        <span className="flex items-center gap-1">
          {t.status !== 'ready' && <Chip tone={t.status === 'failed' ? 'bad' : 'neutral'}>{STATUS_LABEL[t.status]}</Chip>}
          {t.origin === 'search' && isAdmin && (
            <Button variant="ghost" size="icon-sm" onClick={onDelete} disabled={remove.isPending} aria-label={`Delete ${t.name}`} title="Delete this map">
              <Trash2 />
            </Button>
          )}
        </span>
      </div>
      {t.description && <p className="line-clamp-2 text-[13px] leading-relaxed text-fg-2">{t.description}</p>}
      {t.last_change && <LastChange change={t.last_change} />}
      <p className="mt-auto font-mono text-[12px] text-fg-3 tabular-nums">
        {isBuilding(t.status) ? t.status_detail ?? 'Waiting to build' : `${t.paper_count ?? 0} papers · ${t.milestone_count ?? 0} milestones`}
      </p>
    </Link>
  )
}

function LastChange({ change: c }: { change: NonNullable<EvolutionTopic['last_change']> }) {
  const parts = [
    c.new_milestones > 0 && `${c.new_milestones} new ${c.new_milestones === 1 ? 'milestone' : 'milestones'}`,
    c.solved_gaps > 0 && `${c.solved_gaps} ${c.solved_gaps === 1 ? 'gap' : 'gaps'} solved`,
    c.new_gaps > 0 && `${c.new_gaps} new ${c.new_gaps === 1 ? 'gap' : 'gaps'}`,
    c.papers_added > 0 && `${c.papers_added} new papers`,
  ].filter(Boolean)
  return <p className="text-[12px] text-accent-ink">Updated {timeAgo(c.taken_at)}: {parts.join(', ')}</p>
}

/** One map with its tabs. Behind a share link (a read-only map scope) it leaves out what needs an account. */
export function TopicView({ slug }: { slug: string }) {
  const { readOnly } = useMapScope()
  const [params, setParams] = useSearchParams()
  const tabParam = params.get('tab') ?? 'map'
  const tab = (TAB_IDS.has(tabParam) && (!readOnly || SHARED_TABS.has(tabParam as Tab)) ? tabParam : 'map') as Tab
  // The tab and the selected paper live in the URL, so other pages can link to a paper in the map.
  const selectedId = params.get('paper')
  const navigateTo = (t: Tab, paper: string | null) => {
    const next: Record<string, string> = {}
    if (t !== 'map') next.tab = t
    if (paper) next.paper = paper
    setParams(next, { replace: true })
  }
  const setTab = (t: Tab) => navigateTo(t, selectedId)
  const setSelectedId = (id: string | null) => navigateTo(tab, id)
  const [limit, setLimit] = useState(250)
  const [showCitations, setShowCitations] = useState(false)
  const [showLoose, setShowLoose] = useState(false)
  const status = useTopicStatus(slug)
  const current = status.data
  const readable = !!current && !isBuilding(current.status) && current.status !== 'failed'
  const version = current ? `${current.status}:${current.built_at ?? ''}` : ''
  const graph = useTopicGraph(slug, limit, version, readable)
  const timeline = useTopicTimeline(slug, version, readable)
  const selectInMap = (id: string) => navigateTo('map', id)
  const exporter = useRef<GraphExporter | null>(null)
  const { ref: mapRef, on: fullScreen, toggle: toggleFullScreen } = useFullScreen<HTMLDivElement>()

  const back = readOnly ? null : <ButtonLink to="/evolution" variant="ghost" size="sm" className="mb-3 -ml-2.5"><ArrowLeft /> Evolution</ButtonLink>

  if (status.isLoading) {
    return <>{back}<Spinner label="Loading the topic…" /></>
  }
  if (status.error || !current) {
    return <>{back}<Notice tone="error" title="This topic could not be loaded">It may not exist, or the API is not running.</Notice></>
  }
  if (isBuilding(current.status)) {
    return <>{back}<BuildProgress topic={current} /></>
  }
  if (current.status === 'failed') {
    return <>{back}<BuildFailed topic={current} /></>
  }
  if (graph.isLoading || timeline.isLoading) {
    return <>{back}<Spinner label="Loading the topic…" /></>
  }
  if (graph.error || !graph.data || !timeline.data) {
    return <>{back}<Notice tone="error" title="This topic could not be loaded">It may not exist, or the API is not running.</Notice></>
  }
  const { topic, nodes, edges, loose_edges, total_papers } = graph.data
  if (nodes.length === 0) {
    return (
      <>
        {back}
        <Notice tone="warn" title={`No papers in ${topic.name} yet`}>
          {current.origin === 'search'
            ? 'No papers were linked to the anchor papers. Delete this map and search again with other anchors or a broader topic.'
            : <>Build it with <code>python3 scripts/build_evolution_topic.py {topic.slug}</code>.</>}
          {current.status_detail && <span className="mt-1 block">{current.status_detail}</span>}
        </Notice>
        {current.origin === 'search' && <SearchTopicActions topic={current} className="mt-3" />}
      </>
    )
  }
  const milestones = nodes.filter((n) => n.is_milestone).length
  const s2Skipped = String(current.build_stats?.s2 ?? '').startsWith('skipped')

  return (
    <div className="grid gap-6">
      <div>
        {back}
        <PageHeader
          className="pb-0"
          title={topic.name}
          description={topic.description}
          actions={
            <span className="flex flex-wrap items-center justify-end gap-3">
              {current.status === 'refining' && (
                <span title="Embedding the abstracts to drop papers that only mention the topic; the map updates when done">
                  <Chip><Spinner className="h-3 w-3" /> Refining</Chip>
                </span>
              )}
              <span className="font-mono text-[12px] text-fg-3 tabular-nums">
                {total_papers} papers · {milestones} milestones · built {topic.built_at ? new Date(topic.built_at).toLocaleDateString() : '—'}
              </span>
              {!readOnly && current.id && <FollowButton target={{ kind: 'map', topic_id: current.id }} />}
              {!readOnly && <ShareMenu slug={slug} name={topic.name} />}
              <ExportMenu slug={slug} filename={topic.slug} exporter={() => exporter.current} />
              {!readOnly && topic.built_at && <WriteReviewButton slug={slug} />}
              {!readOnly && current.origin === 'search' && <SearchTopicActions topic={current} />}
            </span>
          }
        />
        {!readOnly && current.origin === 'search' && s2Skipped && (
          <Notice className="mt-3 max-w-3xl" title="Built from OpenAlex alone">
            Semantic Scholar was skipped ({current.build_stats.s2?.replace(/^skipped \((.*)\)$/, '$1')}), so recent arXiv papers may be missing citations. Add a key in Settings, then rebuild.
          </Notice>
        )}
      </div>

      <section className="grid gap-2.5">
        <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Milestones</h2>
        <TimelineStrip timeline={timeline.data} selectedId={selectedId} onSelect={selectInMap} />
      </section>

      <div className="flex flex-wrap items-center gap-1 border-b border-line" role="tablist" aria-label="Views">
        {TABS.filter((t) => !readOnly || SHARED_TABS.has(t.id)).map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id || (id === 'map' && tab === 'no-full-text')}
            onClick={() => setTab(id)}
            className={cn('-mb-px border-b-2 px-3 py-2 text-[13px] transition-colors', tab === id || (id === 'map' && tab === 'no-full-text') ? 'border-accent text-fg' : 'border-transparent text-fg-3 hover:text-fg-2')}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'map' ? (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="grid min-w-0 gap-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px] text-fg-2">
              <span className="flex items-center gap-2">
                Papers
                <Segmented label="Papers shown" value={String(limit)} options={LIMITS} onChange={(v) => setLimit(Number(v))} />
              </span>
              <label className="flex items-center gap-2">
                <input id="evolution-citations" type="checkbox" checked={showCitations} onChange={(e) => setShowCitations(e.target.checked)} className="accent-[var(--accent)]" />
                Every citation
              </label>
              <label className="flex items-center gap-2" title="A later paper whose text matches an earlier paper's stated gap, with no citation needed">
                <input id="evolution-loose" type="checkbox" checked={showLoose} onChange={(e) => setShowLoose(e.target.checked)} className="accent-[var(--accent)]" />
                Loose links ({loose_edges.length})
              </label>
              <Legend />
              <span className="ml-auto flex items-center gap-1">
                {timeline.data.without_full_text.length > 0 && (
                  <Button variant="ghost" size="sm" onClick={() => setTab('no-full-text')} title="Notable papers whose full text is not openly available, so their gaps and citing sentences are missing">
                    Without full text ({timeline.data.without_full_text.length})
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={toggleFullScreen} title="Show only the map, on the whole screen">
                  <Maximize2 /> Full screen
                </Button>
              </span>
            </div>
            {/* Full screen shows the map alone; a selected paper's thread still lights up, and its panel is there on the way back. */}
            <div ref={mapRef} className={cn('relative', fullScreen && 'fixed inset-0 z-[60] bg-[var(--map-bg)]')}>
              <EvolutionGraph
                nodes={nodes}
                edges={edges}
                looseEdges={showLoose ? loose_edges : []}
                selectedId={selectedId}
                onSelect={setSelectedId}
                showCitations={showCitations}
                onExporter={(e) => { exporter.current = e }}
                className={fullScreen ? 'h-full rounded-none border-0' : undefined}
              />
              {fullScreen && (
                <Button variant="secondary" size="sm" className="absolute top-3 right-3 z-20" onClick={toggleFullScreen} title="Leave full screen (Esc)">
                  <Minimize2 /> Exit full screen
                </Button>
              )}
            </div>
          </div>
          {selectedId ? (
            <MapPaperPanel slug={slug} paperId={selectedId} onSelect={setSelectedId} onClose={() => setSelectedId(null)} />
          ) : (
            <aside className="grid content-start gap-5">
              <p className="rounded-xl border border-line bg-surface p-4 text-[13px] text-fg-2">
                Select a paper in the map, or a milestone above. A thread then traces what the paper built on and what built on it.
              </p>
              {!readOnly && <NewInMaps topic={slug} limit={5} />}
            </aside>
          )}
        </div>
      ) : tab === 'path' ? (
        <Suspense fallback={<Spinner />}><ReadingPath slug={slug} onSelect={selectInMap} /></Suspense>
      ) : tab === 'gaps' ? (
        <GapsView slug={slug} onSelect={selectInMap} />
      ) : tab === 'ask' ? (
        <Suspense fallback={<Spinner />}><AskMap slug={slug} topicName={topic.name} /></Suspense>
      ) : tab === 'people' ? (
        <Suspense fallback={<Spinner />}><PeopleView slug={slug} onSelect={selectInMap} /></Suspense>
      ) : tab === 'links' ? (
        <Suspense fallback={<Spinner />}><LinksView slug={slug} onSelect={selectInMap} /></Suspense>
      ) : tab === 'changes' ? (
        <Suspense fallback={<Spinner />}><ChangesView slug={slug} busy={isBusy(current.status)} onSelect={selectInMap} /></Suspense>
      ) : (
        <div className="grid gap-3">
          <Button variant="ghost" size="sm" className="-ml-2.5 justify-self-start" onClick={() => setTab('map')}><ArrowLeft /> Back to the map</Button>
          <NoFullTextList papers={timeline.data.without_full_text} onSelect={selectInMap} />
        </div>
      )}
    </div>
  )
}

function BuildProgress({ topic }: { topic: EvolutionTopic }) {
  return (
    <div className="grid max-w-2xl gap-4 rounded-xl border border-line bg-surface p-5">
      <div className="flex items-center gap-3">
        <Spinner className="h-5 w-5" />
        <div className="grid gap-0.5">
          <h1 className="text-[15px] font-medium text-fg">{topic.status === 'pending' ? 'Waiting to build' : 'Building'} the map for {topic.name}</h1>
          <p className="text-[13px] text-fg-2">{topic.status_detail ?? 'Starting'}</p>
        </div>
      </div>
      <p className="text-[12.5px] text-fg-3">
        Collecting the anchors’ references and citing papers, then scoring milestones. This usually takes a few minutes; the map opens here by itself, and you can leave the page meanwhile.
        {topic.status === 'pending' && ' Builds run one at a time, so this one may wait for another job on the evolution worker.'}
      </p>
    </div>
  )
}

function BuildFailed({ topic }: { topic: EvolutionTopic }) {
  return (
    <div className="grid max-w-2xl gap-3">
      <Notice tone="error" title={`The map for ${topic.name} could not be built`}>
        {topic.status_detail ?? 'The build stopped without a message.'}
        {topic.origin !== 'search' && <span className="mt-1 block">Rebuild it with <code>python3 scripts/build_evolution_topic.py {topic.slug}</code>.</span>}
      </Notice>
      {topic.origin === 'search' && <SearchTopicActions topic={topic} />}
    </div>
  )
}

/** Rebuild (for instance once a Semantic Scholar key is set) and delete, for maps built from a search. Admins only:
 *  maps are shared by every user. */
function SearchTopicActions({ topic, className }: { topic: EvolutionTopic; className?: string }) {
  const navigate = useNavigate()
  const rebuild = useRebuildTopic(topic.slug)
  const remove = useDeleteTopic()
  const isAdmin = useIsAdmin()
  if (!isAdmin) return null
  const busy = topic.status === 'refining' || isBuilding(topic.status)
  const onDelete = () => {
    if (window.confirm(`Delete the map for “${topic.name}”? Its papers stay available to other maps.`)) {
      remove.mutate(topic.slug, { onSuccess: () => navigate('/evolution') })
    }
  }
  return (
    <span className={cn('flex items-center gap-1', className)}>
      <Button variant="secondary" size="sm" onClick={() => rebuild.mutate()} disabled={busy || rebuild.isPending} title="Build this map again">
        <RefreshCw /> Rebuild
      </Button>
      <Button variant="ghost" size="sm" onClick={onDelete} disabled={remove.isPending} title="Delete this map">
        <Trash2 /> Delete
      </Button>
      {(rebuild.error || remove.error) && (
        <span className="text-[12px] text-bad">{apiErrorMessage(rebuild.error ?? remove.error, 'That did not work')}</span>
      )}
    </span>
  )
}

function Legend() {
  const entry = (mark: ReactNode, label: string, meaning: string) => (
    <span className="flex items-center gap-1.5">
      {mark}
      <span>{label}<InfoTip label={label} text={meaning} /></span>
    </span>
  )
  const dot = (style: CSSProperties) => <span className="inline-block h-2.5 w-2.5 rounded-full" style={style} />
  const line = (colour: string) => <span className={cn('inline-block h-0.5 w-4', colour)} />
  return (
    <span className="flex flex-wrap items-center gap-3 text-fg-3">
      {entry(dot({ background: 'var(--accent)' }), 'Milestone',
        'A key method paper of the topic, picked era by era for how much later work cites and builds on it.')}
      {entry(dot({ boxShadow: 'inset 0 0 0 2px var(--fg-2)' }), 'On the main path',
        'Part of the citation chain that carries the most of the field, from its oldest papers to its newest.')}
      {entry(dot({ boxShadow: 'inset 0 0 0 2px var(--warn)' }), 'Seed paper',
        'One of the papers the map was built from; the rest were found through their references and citers.')}
      {entry(line('bg-bad'), 'Takes on a stated limitation',
        'A later paper that cites an earlier one in a sentence addressing or criticising a limitation of it.')}
      {entry(line('bg-warn'), 'Loose link',
        "A later paper whose text matches a gap an earlier paper stated, though it doesn't cite it.")}
    </span>
  )
}

function NoFullTextList({ papers, onSelect }: { papers: EvolutionNode[]; onSelect: (id: string) => void }) {
  if (papers.length === 0) {
    return <p className="text-[13px] text-fg-2">Every notable paper in this topic has openly available full text.</p>
  }
  return (
    <div className="grid gap-3">
      <p className="max-w-3xl text-[13px] text-fg-2">
        Notable papers whose full text is not openly available. They stay in the map from their metadata and citations, but their sections cannot be read for open problems.
      </p>
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {papers.map((p) => (
          <li key={p.id} className="grid grid-cols-[3.5rem_minmax(0,1fr)_auto] items-baseline gap-3 px-4 py-2.5">
            <span className="font-mono text-[12px] text-fg-3 tabular-nums">{p.year ?? '—'}</span>
            <button type="button" onClick={() => onSelect(p.id)} className="text-left text-[13px] text-fg hover:underline">
              {p.title}
              {p.is_milestone && <Chip tone="accent" className="ml-2">Milestone</Chip>}
            </button>
            <span className="font-mono text-[12px] text-fg-3 tabular-nums">{p.cited_by_count.toLocaleString()} citations</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
