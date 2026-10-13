import { Link } from 'react-router-dom'
import { GitBranch } from 'lucide-react'
import { useFeedItemEvolution, type CitedMilestone } from '../../features/evolution/api'
import { Chip } from '../../ui/Chip'

/** Where a feed paper sits in the evolution maps, and which of their milestones it cites. Hidden when neither. */
export function PlaceInEvolution({ itemId }: { itemId: string }) {
  const { data } = useFeedItemEvolution(itemId)
  if (!data || (data.places.length === 0 && data.cites.length === 0)) return null
  const byMap = new Map<string, { name: string; papers: CitedMilestone[] }>()
  for (const c of data.cites) {
    const entry = byMap.get(c.topic) ?? { name: c.topic_name, papers: [] }
    entry.papers.push(c)
    byMap.set(c.topic, entry)
  }

  return (
    <section className="grid gap-2.5">
      <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-fg-3">Place in Evolution</h3>
      {data.places.map((p) => (
        <div key={p.topic.slug} className="grid gap-1.5 rounded-lg border border-line bg-surface-2/40 px-3 py-2.5 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/evolution/${p.topic.slug}?paper=${p.paper_id}`} className="inline-flex items-center gap-1.5 font-medium text-fg hover:underline">
              <GitBranch className="h-3.5 w-3.5 text-accent" aria-hidden="true" /> {p.topic.name}
            </Link>
            {p.is_milestone && <Chip tone="accent">Milestone</Chip>}
            {p.on_main_path && <Chip>On the main path</Chip>}
            {p.kind !== 'method' && <Chip>{p.kind}</Chip>}
          </div>
          <p className="text-[12.5px] text-fg-2">
            {p.era && <>Era {p.era[0] === p.era[1] ? p.era[0] : `${p.era[0]}–${p.era[1]}`} · </>}
            #{p.rank} of {p.of} papers by score
            {p.gaps_stated_count > 0 && <> · states {p.gaps_stated_count} {p.gaps_stated_count === 1 ? 'gap' : 'gaps'}</>}
            {p.solves.length > 0 && <> · takes on limitations of {p.solves.length} earlier {p.solves.length === 1 ? 'paper' : 'papers'}</>}
            {p.loose_matches > 0 && <> · its text matches {p.loose_matches} earlier {p.loose_matches === 1 ? 'gap' : 'gaps'}</>}
          </p>
          {p.gaps_stated[0] && <p className="border-l-2 border-line pl-2.5 text-[12.5px] italic leading-relaxed text-fg-2">“{p.gaps_stated[0]}”</p>}
        </div>
      ))}
      {byMap.size > 0 && (
        <div className="grid gap-1.5 text-[13px]">
          <p className="text-fg-2">Cites milestones in your maps:</p>
          <ul className="grid gap-1">
            {[...byMap].map(([slug, m]) => (
              <li key={slug} className="flex flex-wrap items-center gap-1.5">
                <Link to={`/evolution/${slug}`} className="text-fg hover:underline">{m.name}</Link>
                <span className="text-fg-3">·</span>
                {m.papers.map((c) => (
                  <Link key={c.paper_id} to={`/evolution/${slug}?paper=${c.paper_id}`} title={c.title}>
                    <Chip className="hover:border-line-strong">{c.named_method ?? c.title}</Chip>
                  </Link>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
