import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { GitBranch, Loader2, Search } from 'lucide-react'
import { Alert } from '../../components/shared/Alert'
import { EvolutionGraph } from './EvolutionGraph'
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
  { value: 80, label: '80 papers' },
  { value: 250, label: '250 papers' },
  { value: 600, label: '600 papers' },
]

export function EvolutionPage() {
  const { slug } = useParams<{ slug: string }>()
  return (
    <div className="flex-1 flex flex-col min-h-screen">
      <div className="sticky top-0 z-20 glass-base border-b border-white/5 pt-28 pb-8 px-8 backdrop-blur-xl">
        <div className="max-w-[1400px] mx-auto flex flex-col gap-5">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-accent-primary/10 border border-accent-primary/20 flex items-center justify-center text-accent-primary shadow-glow-primary">
              <GitBranch className="w-4 h-4" />
            </div>
            <h1 className="text-3xl font-display font-bold text-text-primary tracking-tight">
              Research <span className="text-accent-primary">Evolution</span>
            </h1>
          </div>
          <TopicSearch />
        </div>
      </div>
      <div className="flex-1 w-full max-w-[1400px] mx-auto px-6 py-10 md:px-12">
        {slug ? <TopicView slug={slug} /> : <TopicList />}
      </div>
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
    <div className="flex flex-col gap-3 max-w-2xl">
      <form onSubmit={onSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-ghost pointer-events-none" />
          <input
            id="evolution-topic-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search a research topic, e.g. object detection or LoRA"
            maxLength={200}
            className="w-full pl-10 pr-3 py-2.5 rounded-lg border border-border-subtle bg-glass-fill text-text-primary placeholder:text-text-ghost focus:outline-none focus:border-accent-primary/60 focus:ring-1 focus:ring-accent-primary/30"
          />
        </div>
        <button type="submit" disabled={pending || !query.trim()} className="btn-glass-primary rounded-lg px-4 disabled:opacity-50">
          {pending ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Show evolution'}
        </button>
      </form>
      {failed && <Alert type="error">Search failed. Check that the API is running and try again.</Alert>}
      {result && !result.found && (
        <Alert type="info" title={result.message}>
          Topics are built ahead of time. Available now: {result.available.join(', ') || 'none yet'}.
        </Alert>
      )}
    </div>
  )
}

function TopicList() {
  const { data: topics, isLoading, error } = useEvolutionTopics()
  if (isLoading) return <p className="text-sm text-text-muted">Loading topics…</p>
  if (error) return <Alert type="error" title="Could not load topics">Check that the API is running.</Alert>
  if (!topics?.length) {
    return (
      <Alert type="info" title="No topics yet">
        Seed and build one with <code>python3 scripts/seed_evolution_topics.py</code> and{' '}
        <code>python3 scripts/build_evolution_topic.py --all</code>.
      </Alert>
    )
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      {topics.map((t) => (
        <Link
          key={t.slug}
          to={`/evolution/${t.slug}`}
          className="glass-opaque hover:glass-float rounded-2xl p-6 border border-white/5 hover:border-accent-primary/30 transition-all flex flex-col gap-3"
        >
          <div className="flex items-start justify-between gap-4">
            <h3 className="font-display font-bold text-lg text-text-primary">{t.name}</h3>
            <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">{t.status}</span>
          </div>
          {t.description && <p className="text-[13px] text-text-secondary leading-relaxed">{t.description}</p>}
          <p className="text-[12px] font-mono text-text-muted tabular-nums">
            {t.paper_count ?? 0} papers · {t.milestone_count ?? 0} milestones
          </p>
        </Link>
      ))}
    </div>
  )
}

function TopicView({ slug }: { slug: string }) {
  const [limit, setLimit] = useState(250)
  const [showCitations, setShowCitations] = useState(false)
  const [tab, setTab] = useState<'graph' | 'no-full-text'>('graph')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const graph = useTopicGraph(slug, limit)
  const timeline = useTopicTimeline(slug)

  if (graph.isLoading || timeline.isLoading) {
    return <p className="flex items-center gap-2 text-sm text-text-muted"><Loader2 className="w-4 h-4 animate-spin" /> Loading the topic…</p>
  }
  if (graph.error || !graph.data || !timeline.data) {
    return <Alert type="error" title="Could not load this topic">It may not exist, or the API is not running.</Alert>
  }
  const { topic, nodes, edges, total_papers } = graph.data
  if (topic.status !== 'ready' || nodes.length === 0) {
    return (
      <Alert type="warning" title={`${topic.name} is ${topic.status}`}>
        Build it with <code>python3 scripts/build_evolution_topic.py {topic.slug}</code>.
        {topic.status_detail && <span className="block mt-1 opacity-80">{topic.status_detail}</span>}
      </Alert>
    )
  }
  const milestones = nodes.filter((n) => n.is_milestone).length

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h2 className="text-2xl font-display font-bold text-text-primary">{topic.name}</h2>
        {topic.description && <p className="text-sm text-text-secondary max-w-3xl">{topic.description}</p>}
        <p className="text-[12px] font-mono text-text-muted tabular-nums">
          {total_papers} papers · {milestones} milestones · built {topic.built_at ? new Date(topic.built_at).toLocaleDateString() : '—'}
        </p>
      </header>

      <section className="flex flex-col gap-3">
        <h3 className="text-[11px] font-display font-bold tracking-[0.15em] uppercase text-text-muted">Milestones</h3>
        <TimelineStrip timeline={timeline.data} selectedId={selectedId} onSelect={setSelectedId} />
      </section>

      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle">
        {(['graph', 'no-full-text'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-[13px] font-medium -mb-px border-b-2 transition-colors ${
              tab === t ? 'border-accent-primary text-text-primary' : 'border-transparent text-text-muted hover:text-text-secondary'
            }`}
          >
            {t === 'graph' ? 'Citation graph' : `Without full text (${timeline.data.without_full_text.length})`}
          </button>
        ))}
      </div>

      {tab === 'graph' ? (
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-5 items-start">
          <div className="flex flex-col gap-3 min-w-0">
            <div className="flex flex-wrap items-center gap-4 text-[12px] text-text-secondary">
              <label className="flex items-center gap-2">
                Show
                <select
                  id="evolution-limit"
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  className="px-2 py-1 rounded-md border border-border-subtle bg-glass-fill text-text-primary"
                >
                  {LIMITS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-2">
                <input id="evolution-citations" type="checkbox" checked={showCitations} onChange={(e) => setShowCitations(e.target.checked)} />
                Show all citations
              </label>
              <Legend />
            </div>
            <EvolutionGraph nodes={nodes} edges={edges} selectedId={selectedId} onSelect={setSelectedId} showCitations={showCitations} />
          </div>
          {selectedId ? (
            <PaperPanel slug={slug} paperId={selectedId} onSelect={setSelectedId} onClose={() => setSelectedId(null)} />
          ) : (
            <aside className="glass-base rounded-xl border border-border-subtle p-5 text-sm text-text-muted">
              Select a paper in the graph or the milestone strip to see where it came from and what built on it.
            </aside>
          )}
        </div>
      ) : (
        <NoFullTextList papers={timeline.data.without_full_text} onSelect={(id) => { setSelectedId(id); setTab('graph') }} />
      )}
    </div>
  )
}

function Legend() {
  const item = (swatch: string, label: string) => (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block w-2.5 h-2.5 rounded-full ${swatch}`} />
      {label}
    </span>
  )
  return (
    <span className="flex flex-wrap items-center gap-3 text-text-muted">
      {item('bg-accent-primary', 'Milestone')}
      {item('border-2 border-accent-tertiary', 'On the main path')}
      {item('border-2 border-accent-warning', 'Seed paper')}
      <span className="flex items-center gap-1.5">
        <span className="inline-block w-4 h-0.5 bg-accent-critical" />
        Takes on a stated limitation
      </span>
    </span>
  )
}

function NoFullTextList({ papers, onSelect }: { papers: EvolutionNode[]; onSelect: (id: string) => void }) {
  if (papers.length === 0) {
    return <p className="text-sm text-text-muted">Every notable paper in this topic has openly available full text.</p>
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-text-secondary max-w-3xl">
        Notable papers whose full text is not openly available. They stay in the graph from their metadata and
        citations, but their sections cannot be analysed for gaps.
      </p>
      <ul className="flex flex-col divide-y divide-border-subtle">
        {papers.map((p) => (
          <li key={p.id} className="py-3 grid grid-cols-[3.5rem_1fr_auto] gap-3 items-baseline">
            <span className="font-mono text-[12px] text-text-muted tabular-nums">{p.year ?? '—'}</span>
            <button onClick={() => onSelect(p.id)} className="text-left text-[13px] text-text-primary hover:text-accent-primary">
              {p.title}
              {p.is_milestone && <span className="ml-2 text-[10px] font-mono uppercase text-accent-primary">milestone</span>}
            </button>
            <span className="font-mono text-[12px] text-text-muted tabular-nums">{p.cited_by_count.toLocaleString()} cites</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
