import { Link } from 'react-router-dom'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { useTopicLinks, type LinkPaper } from './api'

interface LinksViewProps {
  slug: string
  onSelect: (id: string) => void
}

const label = (p: LinkPaper) => p.named_method ?? p.title ?? 'Untitled'

/** How this map connects to the others: shared papers, and milestones borrowed and lent. */
export function LinksView({ slug, onSelect }: LinksViewProps) {
  const { data, isLoading, error } = useTopicLinks(slug)
  if (isLoading) return <Spinner label="Comparing the maps…" />
  if (error || !data) return <Notice tone="error" title="The links could not be loaded">Check that the API is running.</Notice>
  const empty = !data.shared.total && !data.borrowed.length && !data.lent.length
  if (empty) return <Notice title="No links yet">This map shares no papers or citations with the other maps.</Notice>

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2.5">
          <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Borrowed from other maps</h2>
          <p className="text-[12.5px] text-fg-2">Milestones of other maps that this map’s papers cite, by how many of them cite it.</p>
          {data.borrowed.length === 0 ? <p className="text-[13px] text-fg-3">None.</p> : (
            <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
              {data.borrowed.map((p) => (
                <li key={p.id} className="flex items-baseline gap-3 px-4 py-2.5 text-[13px]">
                  <span className="w-8 shrink-0 text-right font-mono text-[12px] text-accent tabular-nums" title="Papers in this map citing it">{p.citing_papers}</span>
                  <Link to={`/evolution/${p.from.topic}?paper=${p.id}`} className="min-w-0 flex-1 truncate text-fg hover:underline" title={p.title ?? undefined}>
                    {label(p)} <span className="text-fg-3">({p.year ?? 'n.d.'})</span>
                  </Link>
                  <span className="max-w-[40%] truncate text-[12px] text-fg-3" title={p.from.topic_name}>{p.from.topic_name}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-2.5">
          <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Lent to other maps</h2>
          <p className="text-[12.5px] text-fg-2">This map’s milestones that papers of other maps cite.</p>
          {data.lent.length === 0 ? <p className="text-[13px] text-fg-3">None.</p> : (
            <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
              {data.lent.map((p) => (
                <li key={p.id} className="flex items-baseline gap-3 px-4 py-2.5 text-[13px]">
                  <span className="w-8 shrink-0 text-right font-mono text-[12px] text-accent tabular-nums" title="Papers in other maps citing it">{p.citing_papers}</span>
                  <button type="button" onClick={() => onSelect(p.id)} className="min-w-0 flex-1 truncate text-left text-fg hover:underline" title={p.title ?? undefined}>
                    {label(p)} <span className="text-fg-3">({p.year ?? 'n.d.'})</span>
                  </button>
                  <span className="max-w-[40%] truncate text-[12px] text-fg-3" title={Object.entries(p.by).map(([m, n]) => `${m}: ${n}`).join(', ')}>
                    {Object.keys(p.by).slice(0, 2).join(', ')}{Object.keys(p.by).length > 2 && ' …'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2.5">
        <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Shared papers · {data.shared.total}</h2>
        <p className="text-[12.5px] text-fg-2">Papers that are part of this map and of others, milestones first.</p>
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-1.5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          {data.shared.papers.map((p) => (
            <li key={p.id} className="flex min-w-0 flex-wrap items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-[13px]">
              <button type="button" onClick={() => onSelect(p.id)} className="min-w-0 truncate text-left text-fg hover:underline" title={p.title ?? undefined}>
                {label(p)} <span className="text-fg-3">({p.year ?? 'n.d.'})</span>
              </button>
              {p.is_milestone && <Chip tone="accent">milestone here</Chip>}
              {p.elsewhere.map((e) => (
                <Link key={e.topic} to={`/evolution/${e.topic}?paper=${p.id}`}>
                  <Chip className="hover:border-line-strong">{e.topic_name}{e.milestone && ' · milestone'}</Chip>
                </Link>
              ))}
            </li>
          ))}
        </ul>
      </section>

    </div>
  )
}
