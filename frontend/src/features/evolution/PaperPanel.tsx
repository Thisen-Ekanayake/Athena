import { useState } from 'react'
import { ExternalLink, Loader2, Pin, PinOff, RotateCcw, X } from 'lucide-react'
import { usePaperDetail, useSetMilestone, type EvolutionNode, type LooseMatch, type PaperGap, type StrictLink } from './api'

interface PaperPanelProps {
  slug: string
  paperId: string
  onSelect: (id: string) => void
  onClose: () => void
}

const SCORE_LABELS: Record<string, string> = {
  citations: 'Citations for its years',
  in_degree: 'Cited within the topic',
  pagerank: 'Graph importance',
  flow: 'Citation paths through it',
  relevance: 'Topic keywords',
  specificity: 'Share of citations from the topic',
  named_method: 'Named method',
}

const YEAR_SOURCE: Record<string, string> = {
  seed: 'from the topic seeds',
  arxiv: 'from its arXiv ID',
  citers: 'inferred from when it was first cited',
  openalex: 'from OpenAlex',
}

export function PaperPanel({ slug, paperId, onSelect, onClose }: PaperPanelProps) {
  const { data: paper, isLoading, error } = usePaperDetail(slug, paperId)
  const setMilestone = useSetMilestone(slug)
  const [note, setNote] = useState('')
  const [showAbstract, setShowAbstract] = useState(false)

  if (isLoading) {
    return (
      <aside className="glass-base rounded-xl border border-border-subtle p-5 flex items-center gap-2 text-sm text-text-muted">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading paper…
      </aside>
    )
  }
  if (error || !paper) {
    return (
      <aside className="glass-base rounded-xl border border-border-subtle p-5 text-sm text-text-muted">
        This paper could not be loaded.
      </aside>
    )
  }

  const status = paper.milestone_override === 'pin'
    ? 'Milestone (pinned by you)'
    : paper.milestone_override === 'unpin'
      ? 'Not a milestone (unpinned by you)'
      : paper.is_milestone ? 'Milestone (picked automatically)' : 'Not a milestone'

  const act = (action: 'pin' | 'unpin' | 'reset') =>
    setMilestone.mutate({ paperId: paper.id, action, note: note.trim() || undefined })

  return (
    <aside className="glass-base rounded-xl border border-border-subtle p-5 flex flex-col gap-4 text-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-display font-bold text-base text-text-primary leading-snug">{paper.title}</h3>
        <button onClick={onClose} className="p-1 -m-1 text-text-muted hover:text-text-primary" aria-label="Close paper details">
          <X className="w-4 h-4" />
        </button>
      </div>

      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-text-muted">Year</dt>
        <dd className="text-text-secondary tabular-nums">
          {paper.year ?? 'unknown'}
          {paper.year_source && <span className="text-text-muted"> · {YEAR_SOURCE[paper.year_source] ?? paper.year_source}</span>}
        </dd>
        {paper.authors.length > 0 && (
          <>
            <dt className="text-text-muted">Authors</dt>
            <dd className="text-text-secondary">{paper.authors.join(', ')}{paper.authors.length >= 3 ? ' et al.' : ''}</dd>
          </>
        )}
        {paper.venue && (
          <>
            <dt className="text-text-muted">Venue</dt>
            <dd className="text-text-secondary">{paper.venue}</dd>
          </>
        )}
        <dt className="text-text-muted">Citations</dt>
        <dd className="text-text-secondary tabular-nums">
          {paper.cited_by_count.toLocaleString()} overall · {paper.in_degree} within this topic
        </dd>
        <dt className="text-text-muted">Full text</dt>
        <dd className="text-text-secondary">{fullTextLabel(paper)}</dd>
      </dl>

      <a href={paper.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-accent-secondary hover:underline text-[13px]">
        Open paper <ExternalLink className="w-3.5 h-3.5" />
      </a>

      {paper.abstract && (
        <div>
          <button onClick={() => setShowAbstract(!showAbstract)} className="text-[12px] font-medium text-text-muted hover:text-text-primary">
            {showAbstract ? 'Hide abstract' : 'Show abstract'}
          </button>
          {showAbstract && <p className="mt-2 text-[13px] text-text-secondary leading-relaxed">{paper.abstract}</p>}
        </div>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <h4 className="text-[11px] font-display font-bold tracking-[0.12em] uppercase text-text-muted">Milestone score</h4>
          <span className="font-mono text-accent-primary tabular-nums">{paper.milestone_score.toFixed(2)}</span>
        </div>
        {Object.entries(paper.score_detail)
          .filter(([, value]) => value > 0)
          .sort(([, a], [, b]) => b - a)
          .map(([key, value]) => (
            <div key={key} className="grid grid-cols-[1fr_5rem] items-center gap-2 text-[12px]">
              <span className="text-text-secondary">{SCORE_LABELS[key] ?? key}</span>
              <span className="h-1.5 rounded-full bg-border-subtle overflow-hidden">
                <span className="block h-full bg-accent-primary" style={{ width: `${Math.min(100, value * 400)}%` }} />
              </span>
            </div>
          ))}
      </section>

      <section className="flex flex-col gap-2">
        <h4 className="text-[11px] font-display font-bold tracking-[0.12em] uppercase text-text-muted">{status}</h4>
        <input
          id="milestone-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={500}
          placeholder={paper.override_note ?? 'Why? (optional note)'}
          className="w-full px-3 py-2 rounded-md border border-border-subtle bg-glass-fill text-text-primary placeholder:text-text-ghost text-[13px] focus:outline-none focus:border-accent-primary/60"
        />
        <div className="flex flex-wrap gap-2">
          {!paper.is_milestone && (
            <button onClick={() => act('pin')} disabled={setMilestone.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-accent-primary/15 border border-accent-primary/30 text-text-primary text-[12px] hover:bg-accent-primary/25">
              <Pin className="w-3.5 h-3.5" /> Pin as milestone
            </button>
          )}
          {paper.is_milestone && (
            <button onClick={() => act('unpin')} disabled={setMilestone.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border-subtle text-text-secondary text-[12px] hover:text-text-primary">
              <PinOff className="w-3.5 h-3.5" /> Remove milestone
            </button>
          )}
          {paper.milestone_override && (
            <button onClick={() => act('reset')} disabled={setMilestone.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border-subtle text-text-secondary text-[12px] hover:text-text-primary">
              <RotateCcw className="w-3.5 h-3.5" /> Back to automatic
            </button>
          )}
        </div>
        {setMilestone.isError && <p className="text-[12px] text-accent-critical">Saving failed. Check that the API is running and try again.</p>}
      </section>

      <Links
        title="Limitations it takes on"
        hint="Earlier papers whose limitation this paper states, in its own words."
        links={paper.addresses}
        onSelect={onSelect}
      />
      <Links
        title="Its limitations, taken on later"
        hint="Later papers stating a limitation of this one."
        links={paper.addressed_by}
        onSelect={onSelect}
      />

      <Gaps gaps={paper.gaps} onSelect={onSelect} />
      <LooseMatches matches={paper.loose_matches} onSelect={onSelect} />

      <Lineage title="Builds on" papers={paper.builds_on} onSelect={onSelect} />
      <Lineage title="Built upon by" papers={paper.built_upon_by} onSelect={onSelect} />
    </aside>
  )
}

function Lineage({ title, papers, onSelect }: { title: string; papers: EvolutionNode[]; onSelect: (id: string) => void }) {
  if (papers.length === 0) return null
  return (
    <section className="flex flex-col gap-1.5">
      <h4 className="text-[11px] font-display font-bold tracking-[0.12em] uppercase text-text-muted">{title}</h4>
      {papers.map((p) => (
        <button key={p.id} onClick={() => onSelect(p.id)} className="text-left text-[12px] text-text-secondary hover:text-text-primary flex gap-2">
          <span className="font-mono text-text-muted tabular-nums shrink-0">{p.year ?? '—'}</span>
          <span className={p.is_milestone ? 'text-text-primary' : ''}>{p.title}</span>
        </button>
      ))}
    </section>
  )
}

const SECTION_NAMES: Record<string, string> = {
  abstract: 'abstract',
  intro: 'introduction',
  related_work: 'related work',
  method: 'method',
  results: 'results',
  discussion: 'discussion',
  limitations: 'limitations',
  conclusion: 'conclusion',
  future_work: 'future work',
  other: 'other section',
}

function fullTextLabel(paper: { full_text_status: string; full_text: { status?: string; sections?: number } }) {
  if (paper.full_text.status === 'parsed') return `Parsed, ${paper.full_text.sections ?? 0} sections`
  if (paper.full_text.status === 's2_contexts') return 'Not openly available; citing sentences from Semantic Scholar'
  if (paper.full_text_status === 'failed') return 'Could not be parsed'
  return paper.full_text_status === 'unavailable' ? 'Not openly available' : 'Openly available'
}

function Links({ title, hint, links, onSelect }: {
  title: string
  hint: string
  links: StrictLink[]
  onSelect: (id: string) => void
}) {
  if (links.length === 0) return null
  return (
    <section className="flex flex-col gap-2">
      <h4 className="text-[11px] font-display font-bold tracking-[0.12em] uppercase text-text-muted" title={hint}>{title}</h4>
      {links.map(({ paper, evidence }) => (
        <div key={paper.id} className="flex flex-col gap-1">
          <button onClick={() => onSelect(paper.id)} className="text-left text-[12px] text-text-primary hover:text-accent-primary flex gap-2">
            <span className="font-mono text-text-muted tabular-nums shrink-0">{paper.year ?? '—'}</span>
            <span>{paper.named_method ? `${paper.named_method}: ` : ''}{paper.title}</span>
          </button>
          {evidence.slice(0, 2).map((e, i) => (
            <blockquote key={i} className="ml-[2.6rem] pl-2 border-l-2 border-accent-critical/60 text-[12px] text-text-secondary leading-relaxed">
              {e.sentence}
              <span className="block mt-0.5 text-[10px] font-mono uppercase text-text-muted">
                {e.label === 'addresses_limitation' ? 'claims a fix' : 'states a limitation'}
                {e.section_type ? ` · ${SECTION_NAMES[e.section_type] ?? e.section_type}` : ''}
                {e.source === 's2' ? ' · via Semantic Scholar' : ''}
              </span>
            </blockquote>
          ))}
          {evidence.length > 2 && <span className="ml-[2.6rem] text-[11px] text-text-muted">and {evidence.length - 2} more sentences</span>}
        </div>
      ))}
    </section>
  )
}

function Gaps({ gaps, onSelect }: { gaps: PaperGap[]; onSelect: (id: string) => void }) {
  const [all, setAll] = useState(false)
  if (gaps.length === 0) return null
  const own = gaps.filter((g) => g.origin === 'own')
  const shown = [...own, ...gaps.filter((g) => g.origin === 'citing')].slice(0, all ? undefined : 4)
  return (
    <section className="flex flex-col gap-2">
      <h4 className="text-[11px] font-display font-bold tracking-[0.12em] uppercase text-text-muted">
        Gaps <span className="font-mono normal-case tracking-normal">{own.length} stated in it · {gaps.length - own.length} by later papers</span>
      </h4>
      {shown.map((g, i) => (
        <blockquote key={i} className="pl-2 border-l-2 border-accent-warning/60 text-[12px] text-text-secondary leading-relaxed">
          {g.sentence}
          <span className="block mt-0.5 text-[10px] font-mono uppercase text-text-muted">
            {g.origin === 'own' ? `its ${SECTION_NAMES[g.section_type ?? 'other'] ?? 'text'}` : 'stated by '}
            {g.origin === 'citing' && g.stated_by && (
              <button onClick={() => onSelect(g.stated_by!.id)} className="normal-case hover:text-accent-primary">
                {g.stated_by.named_method ?? g.stated_by.title.slice(0, 40)} ({g.stated_by.year})
              </button>
            )}
            {g.theme ? ` · theme: ${g.theme}` : ''}
          </span>
        </blockquote>
      ))}
      {gaps.length > 4 && (
        <button onClick={() => setAll(!all)} className="self-start text-[11px] text-text-muted hover:text-text-primary">
          {all ? 'Show fewer' : `Show all ${gaps.length}`}
        </button>
      )}
    </section>
  )
}

function LooseMatches({ matches, onSelect }: { matches: LooseMatch[]; onSelect: (id: string) => void }) {
  if (matches.length === 0) return null
  return (
    <section className="flex flex-col gap-2">
      <h4 className="text-[11px] font-display font-bold tracking-[0.12em] uppercase text-text-muted" title="A later paper whose text matches one of this paper's gaps; it may not cite it">
        Loose matches
      </h4>
      {matches.map((m) => (
        <div key={m.paper.id} className="flex flex-col gap-1">
          <button onClick={() => onSelect(m.paper.id)} className="text-left text-[12px] text-text-primary hover:text-accent-primary flex gap-2">
            <span className="font-mono text-text-muted tabular-nums shrink-0">{m.paper.year ?? '—'}</span>
            <span>{m.paper.named_method ? `${m.paper.named_method}: ` : ''}{m.paper.title}</span>
          </button>
          <p className="ml-[2.6rem] text-[11px] text-text-muted leading-relaxed">
            similarity <span className="font-mono tabular-nums">{m.score.toFixed(2)}</span>
            {m.cites ? ' · also cites it' : ' · does not cite it'} · its {SECTION_NAMES[m.section_type] ?? m.section_type}:
            {' '}<span className="text-text-secondary">“{m.passage.length > 220 ? `${m.passage.slice(0, 217)}…` : m.passage}”</span>
          </p>
        </div>
      ))}
    </section>
  )
}
