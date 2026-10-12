import { useState } from 'react'
import { ExternalLink, Pin, PinOff, RotateCcw, X } from 'lucide-react'
import { useIsAdmin } from '../../api/queries/auth'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'
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
  const isAdmin = useIsAdmin()  // pinning changes the map for everyone
  const [note, setNote] = useState('')
  const [showAbstract, setShowAbstract] = useState(false)

  if (isLoading) {
    return (
      <aside className="rounded-xl border border-line bg-surface p-4">
        <Spinner label="Loading the paper…" />
      </aside>
    )
  }
  if (error || !paper) {
    return (
      <aside className="rounded-xl border border-line bg-surface p-4 text-[13px] text-fg-2">
        This paper could not be loaded. Check that the API is running.
      </aside>
    )
  }

  const status = paper.milestone_override === 'pin'
    ? 'Milestone (pinned by an admin)'
    : paper.milestone_override === 'unpin'
      ? 'Not a milestone (unpinned by an admin)'
      : paper.is_milestone ? 'Milestone (picked automatically)' : 'Not a milestone'

  const act = (action: 'pin' | 'unpin' | 'reset') =>
    setMilestone.mutate({ paperId: paper.id, action, note: note.trim() || undefined })

  return (
    <aside className="flex max-h-[calc(100vh-7rem)] flex-col gap-4 overflow-y-auto rounded-xl border border-line bg-surface p-4 text-[13px] xl:sticky xl:top-20">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-[15px] leading-snug font-semibold text-fg">{paper.title}</h3>
        <Button variant="ghost" size="icon-sm" className="-mt-1 -mr-1" onClick={onClose} aria-label="Close paper details">
          <X />
        </Button>
      </div>

      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-[13px]">
        <dt className="text-fg-3">Year</dt>
        <dd className="text-fg-2 tabular-nums">
          {paper.year ?? 'unknown'}
          {paper.year_source && <span className="text-fg-3"> · {YEAR_SOURCE[paper.year_source] ?? paper.year_source}</span>}
        </dd>
        {paper.authors.length > 0 && (
          <>
            <dt className="text-fg-3">Authors</dt>
            <dd className="text-fg-2">{paper.authors.join(', ')}{paper.authors.length >= 3 ? ' et al.' : ''}</dd>
          </>
        )}
        {paper.venue && (
          <>
            <dt className="text-fg-3">Venue</dt>
            <dd className="text-fg-2">{paper.venue}</dd>
          </>
        )}
        <dt className="text-fg-3">Citations</dt>
        <dd className="text-fg-2 tabular-nums">
          {paper.cited_by_count.toLocaleString()} overall · {paper.in_degree} within this topic
        </dd>
        <dt className="text-fg-3">Full text</dt>
        <dd className="text-fg-2">{fullTextLabel(paper)}</dd>
      </dl>

      <a href={paper.url} target="_blank" rel="noreferrer" className="inline-flex w-fit items-center gap-1.5 text-[13px] text-accent-ink hover:underline">
        Open the paper <ExternalLink className="h-3.5 w-3.5" />
      </a>

      {paper.abstract && (
        <div>
          <button onClick={() => setShowAbstract(!showAbstract)} className="text-[12px] font-medium text-fg-3 hover:text-fg">
            {showAbstract ? 'Hide abstract' : 'Show abstract'}
          </button>
          {showAbstract && <p className="mt-2 text-[13px] text-fg-2 leading-relaxed">{paper.abstract}</p>}
        </div>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <h4 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Milestone score</h4>
          <span className="font-mono text-accent tabular-nums">{paper.milestone_score.toFixed(2)}</span>
        </div>
        {Object.entries(paper.score_detail)
          .filter(([, value]) => value > 0)
          .sort(([, a], [, b]) => b - a)
          .map(([key, value]) => (
            <div key={key} className="grid grid-cols-[1fr_5rem] items-center gap-2 text-[12px]">
              <span className="text-fg-2">{SCORE_LABELS[key] ?? key}</span>
              <span className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
                <span className="block h-full bg-accent" style={{ width: `${Math.min(100, value * 400)}%` }} />
              </span>
            </div>
          ))}
      </section>

      <section className="flex flex-col gap-2">
        <h4 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">{status}</h4>
        {isAdmin && (<>
        <input
          id="milestone-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={500}
          placeholder={paper.override_note ?? 'Why? (optional note)'}
          className="w-full px-3 py-2 rounded-lg border border-line bg-surface-2 text-fg placeholder:text-fg-3 text-[13px] focus:outline-none focus:border-accent-line"
        />
        <div className="flex flex-wrap gap-2">
          {!paper.is_milestone && (
            <button onClick={() => act('pin')} disabled={setMilestone.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-accent-line bg-accent-soft text-fg text-[12px] hover:bg-accent-soft/70">
              <Pin className="w-3.5 h-3.5" /> Pin as milestone
            </button>
          )}
          {paper.is_milestone && (
            <button onClick={() => act('unpin')} disabled={setMilestone.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-line text-fg-2 text-[12px] hover:text-fg">
              <PinOff className="w-3.5 h-3.5" /> Remove milestone
            </button>
          )}
          {paper.milestone_override && (
            <button onClick={() => act('reset')} disabled={setMilestone.isPending} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-line text-fg-2 text-[12px] hover:text-fg">
              <RotateCcw className="w-3.5 h-3.5" /> Back to automatic
            </button>
          )}
        </div>
        {setMilestone.isError && <p className="text-[12px] text-bad">Saving failed. Check that the API is running and try again.</p>}
        </>)}
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
      <h4 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">{title}</h4>
      {papers.map((p) => (
        <button key={p.id} onClick={() => onSelect(p.id)} className="text-left text-[12px] text-fg-2 hover:text-fg flex gap-2">
          <span className="font-mono text-fg-3 tabular-nums shrink-0">{p.year ?? '—'}</span>
          <span className={p.is_milestone ? 'text-fg' : ''}>{p.title}</span>
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
      <h4 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase" title={hint}>{title}</h4>
      {links.map(({ paper, evidence }) => (
        <div key={paper.id} className="flex flex-col gap-1">
          <button onClick={() => onSelect(paper.id)} className="text-left text-[12px] text-fg hover:text-accent flex gap-2">
            <span className="font-mono text-fg-3 tabular-nums shrink-0">{paper.year ?? '—'}</span>
            <span>{paper.named_method ? `${paper.named_method}: ` : ''}{paper.title}</span>
          </button>
          {evidence.slice(0, 2).map((e, i) => (
            <blockquote key={i} className="ml-[2.6rem] pl-2 border-l-2 border-bad/60 text-[12px] text-fg-2 leading-relaxed">
              {e.sentence}
              <span className="block mt-0.5 text-[10px] font-mono uppercase text-fg-3">
                {e.label === 'addresses_limitation' ? 'claims a fix' : 'states a limitation'}
                {e.section_type ? ` · ${SECTION_NAMES[e.section_type] ?? e.section_type}` : ''}
                {e.source === 's2' ? ' · via Semantic Scholar' : ''}
              </span>
            </blockquote>
          ))}
          {evidence.length > 2 && <span className="ml-[2.6rem] text-[11px] text-fg-3">and {evidence.length - 2} more sentences</span>}
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
      <h4 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">
        Gaps <span className="font-mono normal-case tracking-normal">{own.length} stated in it · {gaps.length - own.length} by later papers</span>
      </h4>
      {shown.map((g, i) => (
        <blockquote key={i} className="pl-2 border-l-2 border-warn/60 text-[12px] text-fg-2 leading-relaxed">
          {g.sentence}
          <span className="block mt-0.5 text-[10px] font-mono uppercase text-fg-3">
            {g.origin === 'own' ? `its ${SECTION_NAMES[g.section_type ?? 'other'] ?? 'text'}` : 'stated by '}
            {g.origin === 'citing' && g.stated_by && (
              <button onClick={() => onSelect(g.stated_by!.id)} className="normal-case hover:text-accent">
                {g.stated_by.named_method ?? g.stated_by.title.slice(0, 40)} ({g.stated_by.year})
              </button>
            )}
            {g.theme ? ` · theme: ${g.theme}` : ''}
          </span>
        </blockquote>
      ))}
      {gaps.length > 4 && (
        <button onClick={() => setAll(!all)} className="self-start text-[11px] text-fg-3 hover:text-fg">
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
      <h4 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase" title="A later paper whose text matches one of this paper's gaps; it may not cite it">
        Loose matches
      </h4>
      {matches.map((m) => (
        <div key={m.paper.id} className="flex flex-col gap-1">
          <button onClick={() => onSelect(m.paper.id)} className="text-left text-[12px] text-fg hover:text-accent flex gap-2">
            <span className="font-mono text-fg-3 tabular-nums shrink-0">{m.paper.year ?? '—'}</span>
            <span>{m.paper.named_method ? `${m.paper.named_method}: ` : ''}{m.paper.title}</span>
          </button>
          <p className="ml-[2.6rem] text-[11px] text-fg-3 leading-relaxed">
            similarity <span className="font-mono tabular-nums">{m.score.toFixed(2)}</span>
            {m.cites ? ' · also cites it' : ' · does not cite it'} · its {SECTION_NAMES[m.section_type] ?? m.section_type}:
            {' '}<span className="text-fg-2">“{m.passage.length > 220 ? `${m.passage.slice(0, 217)}…` : m.passage}”</span>
          </p>
        </div>
      ))}
    </section>
  )
}
