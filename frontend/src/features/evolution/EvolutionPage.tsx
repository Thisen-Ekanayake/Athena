import { useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, GitBranch, Search } from 'lucide-react'
import { Button, ButtonLink } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { EmptyState } from '../../ui/EmptyState'
import { Notice } from '../../ui/Notice'
import { PageHeader } from '../../ui/PageHeader'
import { Segmented } from '../../ui/Segmented'
import { Skeleton } from '../../ui/Skeleton'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { EvolutionGraph } from './EvolutionGraph'
import { GapsView } from './GapsView'
import { PaperPanel } from './PaperPanel'
import { TimelineStrip } from './TimelineStrip'
import {
  searchTopics,
  useEvolutionTopics,
  useTopicGraph,
  useTopicTimeline,
  type EvolutionNode,
  type TopicSearchResult,
} from './api'

const LIMITS = [
  { value: '80', label: '80' },
  { value: '250', label: '250' },
  { value: '600', label: '600' },
]

type Tab = 'map' | 'gaps' | 'no-full-text'

/** How a field developed: its lineage of papers, its milestones and the problems still open. */
export function EvolutionPage() {
  const { slug } = useParams<{ slug: string }>()
  return (
    <div className="mx-auto max-w-[1400px]">
      {slug ? (
        <TopicView key={slug} slug={slug} />
      ) : (
        <>
          <PageHeader title="Evolution" description="How a field developed: which papers it grew from, its milestones, and the problems still open." />
          <TopicSearch />
          <TopicList />
        </>
      )}
    </div>
  )
}

function TopicSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [pending, setPending] = useState(false)
  const [result, setResult] = useState<TopicSearchResult | null>(null)
  const [failed, setFailed] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    setPending(true)
    setFailed(false)
    try {
      const found = await searchTopics(q)
      setResult(found)
      if (found.found) navigate(`/evolution/${found.topic.slug}`)
    } catch {
      setFailed(true)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="mb-6 grid max-w-2xl gap-3">
      <form onSubmit={onSubmit} className="flex gap-2">
        <label className="flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-lg border border-line bg-surface px-3 focus-within:border-accent-line">
          <Search className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
          <input
            id="evolution-topic-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a topic, e.g. object detection or LoRA"
            maxLength={200}
            aria-label="Topic"
            className="min-w-0 flex-1 bg-transparent text-[13.5px] text-fg placeholder:text-fg-3 focus:outline-none"
          />
        </label>
        <Button type="submit" variant="primary" className="h-9" disabled={pending || !query.trim()}>
          {pending ? <Spinner className="h-4 w-4" /> : 'Show evolution'}
        </Button>
      </form>
      {failed && <Notice tone="error" title="The search failed">Check that the API is running and try again.</Notice>}
      {result && !result.found && (
        <Notice title={result.message}>Topics are built ahead of time. Available now: {result.available.join(', ') || 'none yet'}.</Notice>
      )}
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
  if (!topics?.length) {
    return (
      <EmptyState icon={GitBranch} title="No research maps yet">
        Seed and build one with <code className="font-mono text-[12px]">python3 scripts/seed_evolution_topics.py</code> and{' '}
        <code className="font-mono text-[12px]">python3 scripts/build_evolution_topic.py --all</code>.
      </EmptyState>
    )
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {topics.map((t) => (
        <Link key={t.slug} to={`/evolution/${t.slug}`} className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2/50">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-[15px] font-medium text-fg">{t.name}</h2>
            {t.status !== 'ready' && <Chip tone={t.status === 'failed' ? 'bad' : 'neutral'}>{t.status}</Chip>}
          </div>
          {t.description && <p className="line-clamp-2 text-[13px] leading-relaxed text-fg-2">{t.description}</p>}
          <p className="mt-auto font-mono text-[12px] text-fg-3 tabular-nums">
            {t.paper_count ?? 0} papers · {t.milestone_count ?? 0} milestones
          </p>
        </Link>
      ))}
    </div>
  )
}

function TopicView({ slug }: { slug: string }) {
  const [params, setParams] = useSearchParams()
  const tabParam = params.get('tab')
  const tab: Tab = tabParam === 'gaps' || tabParam === 'no-full-text' ? tabParam : 'map'
  const setTab = (t: Tab) => setParams(t === 'map' ? {} : { tab: t }, { replace: true })
  const [limit, setLimit] = useState(250)
  const [showCitations, setShowCitations] = useState(false)
  const [showLoose, setShowLoose] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const graph = useTopicGraph(slug, limit)
  const timeline = useTopicTimeline(slug)
  const selectInMap = (id: string) => {
    setSelectedId(id)
    setTab('map')
  }

  const back = <ButtonLink to="/evolution" variant="ghost" size="sm" className="mb-3 -ml-2.5"><ArrowLeft /> Evolution</ButtonLink>

  if (graph.isLoading || timeline.isLoading) {
    return <>{back}<Spinner label="Loading the topic…" /></>
  }
  if (graph.error || !graph.data || !timeline.data) {
    return <>{back}<Notice tone="error" title="This topic could not be loaded">It may not exist, or the API is not running.</Notice></>
  }
  const { topic, nodes, edges, loose_edges, total_papers } = graph.data
  if (topic.status !== 'ready' || nodes.length === 0) {
    return (
      <>
        {back}
        <Notice tone="warn" title={`${topic.name} is ${topic.status}`}>
          Build it with <code>python3 scripts/build_evolution_topic.py {topic.slug}</code>.
          {topic.status_detail && <span className="mt-1 block">{topic.status_detail}</span>}
        </Notice>
      </>
    )
  }
  const milestones = nodes.filter((n) => n.is_milestone).length

  return (
    <div className="grid gap-6">
      <div>
        {back}
        <PageHeader
          className="pb-0"
          title={topic.name}
          description={topic.description}
          actions={
            <span className="font-mono text-[12px] text-fg-3 tabular-nums">
              {total_papers} papers · {milestones} milestones · built {topic.built_at ? new Date(topic.built_at).toLocaleDateString() : '—'}
            </span>
          }
        />
      </div>

      <section className="grid gap-2.5">
        <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Milestones</h2>
        <TimelineStrip timeline={timeline.data} selectedId={selectedId} onSelect={selectInMap} />
      </section>

      <div className="flex flex-wrap items-center gap-1 border-b border-line" role="tablist" aria-label="Views">
        {([
          ['map', 'Lineage map'],
          ['gaps', 'Open problems'],
          ['no-full-text', `Without full text (${timeline.data.without_full_text.length})`],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn('-mb-px border-b-2 px-3 py-2 text-[13px] transition-colors', tab === id ? 'border-accent text-fg' : 'border-transparent text-fg-3 hover:text-fg-2')}
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
            </div>
            <EvolutionGraph
              nodes={nodes}
              edges={edges}
              looseEdges={showLoose ? loose_edges : []}
              selectedId={selectedId}
              onSelect={setSelectedId}
              showCitations={showCitations}
            />
          </div>
          {selectedId ? (
            <PaperPanel slug={slug} paperId={selectedId} onSelect={setSelectedId} onClose={() => setSelectedId(null)} />
          ) : (
            <aside className="rounded-xl border border-line bg-surface p-4 text-[13px] text-fg-2">
              Select a star in the map, or a milestone above. A thread then traces what the paper built on and what built on it.
            </aside>
          )}
        </div>
      ) : tab === 'gaps' ? (
        <GapsView slug={slug} onSelect={selectInMap} />
      ) : (
        <NoFullTextList papers={timeline.data.without_full_text} onSelect={selectInMap} />
      )}
    </div>
  )
}

function Legend() {
  const dot = (style: CSSProperties, label: string) => (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={style} />
      {label}
    </span>
  )
  return (
    <span className="flex flex-wrap items-center gap-3 text-fg-3">
      {dot({ background: 'var(--accent)' }, 'Milestone')}
      {dot({ boxShadow: 'inset 0 0 0 2px var(--fg-2)' }, 'On the main path')}
      {dot({ boxShadow: 'inset 0 0 0 2px var(--warn)' }, 'Seed paper')}
      <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-bad" />Takes on a stated limitation</span>
      <span className="flex items-center gap-1.5"><span className="inline-block w-4 border-t-2 border-dashed border-warn" />Loose link</span>
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
