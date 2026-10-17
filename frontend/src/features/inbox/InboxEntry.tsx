import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, GitBranch, Gauge, History, Layers, Newspaper, Quote, Rss, Search } from 'lucide-react'
import type { InboxEvent, InboxItem, WatchKind } from '../../api/queries/inbox'
import { cn } from '../../ui/cn'
import { timeAgo } from '../../components/items/format'

/** What kind of entry this is, at a glance. */
function KindIcon({ event: e }: { event: InboxEvent }) {
  const props = { className: 'h-3.5 w-3.5 shrink-0 translate-y-[2px] text-fg-3', 'aria-hidden': true }
  const kind = e.kind === 'watch_matches' ? e.payload.watch_kind ?? 'search' : e.kind
  switch (kind) {
    case 'map_new': case 'map': return <GitBranch {...props} />
    case 'map_changes': return <History {...props} />
    case 'feed_citations': return <Quote {...props} />
    case 'digest': return <Newspaper {...props} />
    case 'budget': return <Gauge {...props} />
    case 'source': return <Rss {...props} />
    case 'cluster': return <Layers {...props} />
    default: return <Search {...props} />
  }
}

/** Entries whose papers or sections open in the inbox rather than elsewhere. */
const hasDetails = (e: InboxEvent) => e.kind === 'digest' || !!e.payload.items?.length

const OPEN_LABEL: Record<WatchKind, string> = { map: 'Open the map', search: 'Open the search', source: 'Open the source', cluster: 'Open the cluster' }

/**
 * One inbox entry. In the bell it is a link: entries with details open on the inbox page. On the page
 * (``onToggle`` given) those entries expand in place.
 */
export function Entry({ event: e, onOpen, open, onToggle }: {
  event: InboxEvent
  onOpen?: () => void
  open?: boolean
  onToggle?: () => void
}) {
  const details = hasDetails(e)
  const head = (
    <>
      <span className="flex items-baseline gap-2">
        <KindIcon event={e} />
        <span className="min-w-0 flex-1 text-[13px] font-medium text-fg">{e.title}</span>
        {e.unread && <span className="h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full bg-accent" aria-label="Unread" />}
        <span className="shrink-0 text-[11.5px] text-fg-3">{timeAgo(e.created_at)}</span>
        {onToggle && details && <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 translate-y-[2px] text-fg-3 transition-transform', open && 'rotate-180')} aria-hidden="true" />}
      </span>
      {e.body && <span className={cn('pl-[22px] text-[12.5px] text-fg-2', !open && 'line-clamp-2')}>{e.body}</span>}
    </>
  )
  const cls = 'grid w-full gap-0.5 rounded-lg px-2 py-2 text-left hover:bg-surface-2'

  if (onToggle && details) {
    return (
      <li id={`inbox-${e.id}`} className="scroll-mt-20">
        <button type="button" className={cls} aria-expanded={open} onClick={onToggle}>{head}</button>
        {open && <div className="px-2 pt-1 pb-3 pl-[30px]"><Details event={e} /></div>}
      </li>
    )
  }
  const to = details && !onToggle ? `/inbox?open=${e.id}` : e.link
  return <li>{to ? <Link to={to} onClick={onOpen} className={cls}>{head}</Link> : <div className={cn(cls, 'hover:bg-transparent')}>{head}</div>}</li>
}

function Details({ event: e }: { event: InboxEvent }) {
  if (e.kind === 'digest') return <Digest event={e} />
  const kind: WatchKind = e.kind === 'feed_citations' ? 'map' : e.payload.watch_kind ?? 'search'
  return (
    <div className="grid gap-2">
      <Items items={e.payload.items ?? []} />
      {e.link && <Link to={e.link} className="text-[12.5px] text-accent hover:underline">{OPEN_LABEL[kind]}</Link>}
    </div>
  )
}

function Items({ items }: { items: InboxItem[] }) {
  return (
    <ul className="grid gap-1">
      {items.map((i) => (
        <li key={i.id} className="text-[12.5px] leading-snug">
          <Link to={`/items/${i.id}`} className="text-fg-2 hover:text-fg hover:underline">{i.title}</Link>
          {!!i.cites?.length && <span className="text-fg-3"> · cites {i.cites.join(', ')}</span>}
        </li>
      ))}
    </ul>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-1.5">
      <h3 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">{title}</h3>
      {children}
    </section>
  )
}

function Digest({ event: e }: { event: InboxEvent }) {
  const d = e.payload
  return (
    <div className="grid gap-4">
      {!!d.watches?.length && (
        <Section title="What you follow">
          <div className="grid gap-2.5">
            {d.watches.map((w) => (
              <div key={w.watch_id} className="grid gap-1">
                <p className="text-[12.5px] text-fg">
                  {w.link ? <Link to={w.link} className="font-medium hover:underline">{w.label}</Link> : <span className="font-medium">{w.label}</span>}
                  <span className="text-fg-3"> · {w.count} new</span>
                </p>
                <Items items={w.items} />
              </div>
            ))}
          </div>
        </Section>
      )}
      {!!d.maps?.length && (
        <Section title="Maps you follow">
          <ul className="grid gap-1">
            {d.maps.map((m) => (
              <li key={`${m.slug}-${m.taken_at}`} className="text-[12.5px]">
                <Link to={`/evolution/${m.slug}?tab=changes`} className="font-medium text-fg hover:underline">{m.name}</Link>
                <span className="text-fg-2">: {m.changes.join('; ')}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {!!d.new_maps?.length && (
        <Section title="New maps">
          <ul className="grid gap-1">
            {d.new_maps.map((m) => (
              <li key={m.title} className="text-[12.5px]">
                {m.link ? <Link to={m.link} className="font-medium text-fg hover:underline">{m.title}</Link> : m.title}
                {m.body && <span className="text-fg-3"> · {m.body}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {!!d.citations?.length && (
        <Section title="New papers citing your maps' milestones">
          {d.citations.map((c) => (
            <div key={c.title} className="grid gap-1">
              <p className="text-[12.5px] font-medium text-fg">{c.title}</p>
              <Items items={c.items} />
            </div>
          ))}
        </Section>
      )}
      {!!d.top_papers?.length && (
        <Section title={`Top new in the feed${d.new_items ? ` (of ${d.new_items.toLocaleString()})` : ''}`}>
          <Items items={d.top_papers} />
        </Section>
      )}
    </div>
  )
}
