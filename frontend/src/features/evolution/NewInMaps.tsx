import { Link } from 'react-router-dom'
import { timeAgo } from '../../components/items/format'
import { usePanelStore } from '../../store/panelStore'
import { Chip } from '../../ui/Chip'
import { useNewMapPapers } from './api'

interface NewInMapsProps {
  /** One map's slug; every map when left out. */
  topic?: string
  limit?: number
}

/** Recent feed papers that cite a map's milestones. Renders nothing when there are none. */
export function NewInMaps({ topic, limit = 6 }: NewInMapsProps) {
  const { data } = useNewMapPapers(topic)
  const open = usePanelStore((s) => s.open)
  if (!data?.length) return null
  return (
    <section className="grid min-w-0 gap-2.5">
      <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">
        {topic ? 'New papers citing these milestones' : 'New in your maps'}
      </h2>
      <ul className="grid gap-px overflow-hidden rounded-xl border border-line bg-line">
        {data.slice(0, limit).map((p) => (
          <li key={p.id} className="grid min-w-0 gap-1.5 bg-surface px-4 py-3">
            <button type="button" onClick={() => open(p.id)} className="text-left text-[13.5px] leading-snug font-medium text-fg hover:underline">
              {p.title}
            </button>
            <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
              <span>{timeAgo(p.published_at)} · cites</span>
              {p.cites.slice(0, 4).map((c) => (
                <Link key={`${c.topic}-${c.paper_id}`} to={`/evolution/${c.topic}?paper=${c.paper_id}`} title={`${c.title} — a milestone in ${c.topic_name}`} className="max-w-full min-w-0">
                  {/* Chips don't wrap: a long title is cut short so it stays inside a narrow column. */}
                  <Chip className="max-w-full hover:border-line-strong">
                    <span className="truncate">{c.named_method ?? c.title}{!topic && <span className="text-fg-3"> · {c.topic_name}</span>}</span>
                  </Chip>
                </Link>
              ))}
              {p.cites.length > 4 && <span>and {p.cites.length - 4} more</span>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
