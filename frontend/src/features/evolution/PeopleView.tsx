import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { useTopicPeople, type PeopleEra, type PersonPaper, type RankedAuthor } from './api'

interface PeopleViewProps {
  slug: string
  onSelect: (id: string) => void
}

const eraLabel = (e: { start: number; end: number }) => (e.start === e.end ? String(e.start) : `${e.start}–${e.end}`)

/** Who did the work: the key authors and labs of each era, and who introduced each milestone. */
export function PeopleView({ slug, onSelect }: PeopleViewProps) {
  const { data, isLoading, error } = useTopicPeople(slug)
  if (isLoading) return <Spinner label="Gathering the authors…" />
  if (error || !data) return <Notice tone="error" title="The people could not be loaded">Check that the API is running.</Notice>
  if (data.eras.length === 0) return <Notice title="No authors yet">This map has no on-topic method papers with authors.</Notice>

  return (
    <div className="grid gap-6">
      <section className="grid gap-3 md:grid-cols-2">
        <Ranking title="Key authors" people={data.overall.authors} onSelect={onSelect} />
        <Ranking title="Key labs" people={data.overall.labs} onSelect={onSelect} />
      </section>

      <section className="grid gap-2.5">
        <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">By era</h2>
        <p className="max-w-3xl text-[13px] text-fg-2">
          Authors and labs are ranked by the milestones they wrote, then by the scores of their other papers on the topic in those years.
        </p>
        <ol className="grid gap-3">
          {data.eras.map((e) => <EraRow key={e.start} era={e} onSelect={onSelect} />)}
        </ol>
      </section>

      <section className="grid gap-2.5">
        <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Who introduced each milestone</h2>
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {data.milestones.map((m) => (
            <li key={m.id} className="grid gap-1 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] sm:gap-4">
              <PaperLink paper={m} onSelect={onSelect} />
              <p className="text-[12.5px] leading-relaxed text-fg-2">
                {m.authors.length === 0 ? <span className="text-fg-3">Authors unknown</span> : m.authors.map((a, i) => (
                  <span key={`${a.name}-${i}`}>
                    {i > 0 && ', '}
                    {a.name}
                    {a.institutions.length > 0 && <span className="text-fg-3"> ({a.institutions.join('; ')})</span>}
                  </span>
                ))}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {data.papers_with_ids < data.papers && (
        <p className="text-[12px] text-fg-3">
          {data.papers - data.papers_with_ids} of {data.papers} papers have no OpenAlex author IDs, so their authors are told apart by name only.
        </p>
      )}
    </div>
  )
}

function PaperLink({ paper, onSelect }: { paper: PersonPaper; onSelect: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onSelect(paper.id)} className="min-w-0 text-left text-[13px] text-fg hover:underline" title={paper.title}>
      <span className="mr-1.5 font-mono text-[12px] text-fg-3 tabular-nums">{paper.year ?? '—'}</span>
      {paper.named_method ?? paper.title}
    </button>
  )
}

function Ranking({ title, people, onSelect }: { title: string; people: RankedAuthor[]; onSelect: (id: string) => void }) {
  return (
    <div className="grid content-start gap-2 rounded-xl border border-line bg-surface p-4">
      <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">{title}</h2>
      <ol className="grid gap-1.5">
        {people.map((p, i) => (
          <li key={p.id ?? p.name} className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-2 text-[13px]">
            <span className="font-mono text-[12px] text-fg-3 tabular-nums">{i + 1}</span>
            <span className="min-w-0">
              <span className="text-fg">{p.name}</span>
              <span className="text-fg-3"> · {p.milestones > 0 && `${p.milestones} ${p.milestones === 1 ? 'milestone' : 'milestones'}, `}{p.papers} {p.papers === 1 ? 'paper' : 'papers'} · </span>
              <PaperLink paper={p.best_paper} onSelect={onSelect} />
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function EraRow({ era, onSelect }: { era: PeopleEra; onSelect: (id: string) => void }) {
  return (
    <li className="grid gap-3 rounded-xl border border-line bg-surface p-4 lg:grid-cols-[7rem_minmax(0,1.4fr)_minmax(0,1fr)]">
      <div>
        <p className="font-mono text-[13px] font-medium text-accent tabular-nums">{eraLabel(era)}</p>
        <p className="text-[12px] text-fg-3">{era.papers} {era.papers === 1 ? 'paper' : 'papers'}</p>
      </div>
      <ul className="grid content-start gap-1">
        {era.authors.slice(0, 5).map((a) => (
          <li key={a.id ?? a.name} className="truncate text-[13px] text-fg-2">
            <span className="text-fg">{a.name}</span>
            {a.milestones > 0 && <span className="text-accent-ink"> · {a.milestones === 1 ? 'milestone' : `${a.milestones} milestones`}</span>}
            <span className="text-fg-3"> · </span>
            <PaperLink paper={a.best_paper} onSelect={onSelect} />
          </li>
        ))}
      </ul>
      <ul className="grid content-start gap-1">
        {era.labs.slice(0, 4).map((l) => (
          <li key={l.id ?? l.name} className="truncate text-[12.5px] text-fg-2" title={l.name}>
            {l.name}
            <span className="text-fg-3"> · {l.papers}</span>
          </li>
        ))}
      </ul>
    </li>
  )
}
