import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useInbox, useInboxUnread, useMarkInboxSeen, type InboxEvent } from '../../api/queries/inbox'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { timeAgo } from '../items/format'

/** Map updates, new maps and new papers citing milestones. Opening it marks everything read. */
export function InboxBell() {
  const [open, setOpen] = useState(false)
  const unread = useInboxUnread().data ?? 0
  const inbox = useInbox(open, 15)
  const markSeen = useMarkInboxSeen()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = () => {
    setOpen((v) => !v)
    if (!open && unread > 0) markSeen.mutate()
  }

  return (
    <div ref={ref} className="relative">
      <Button variant="ghost" size="icon" onClick={toggle} aria-expanded={open} aria-label={unread ? `Inbox, ${unread} unread` : 'Inbox'} title="Inbox">
        <Bell />
        {unread > 0 && (
          <span className="absolute top-1 right-1 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 font-mono text-[10px] text-on-primary tabular-nums">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </Button>
      {open && (
        <div className="absolute right-0 z-40 mt-1.5 grid w-[min(360px,calc(100vw-2rem))] gap-1 rounded-xl border border-line bg-surface p-2 shadow-lg">
          <p className="px-2 pt-1 text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Inbox</p>
          {inbox.isLoading ? <Spinner className="m-3" /> : !inbox.data?.events.length ? (
            <p className="px-2 py-3 text-[13px] text-fg-3">Nothing yet. Map refreshes and new papers citing milestones show up here.</p>
          ) : (
            <ul className="grid max-h-[420px] gap-px overflow-y-auto">
              {inbox.data.events.map((e) => <Entry key={e.id} event={e} onOpen={() => setOpen(false)} />)}
            </ul>
          )}
          <Link to="/inbox" onClick={() => setOpen(false)} className="px-2 py-1.5 text-[12.5px] text-fg-2 hover:text-fg">See all</Link>
        </div>
      )}
    </div>
  )
}

export function Entry({ event: e, onOpen }: { event: InboxEvent; onOpen?: () => void }) {
  const inner = (
    <>
      <span className="flex items-baseline gap-2">
        {e.unread && <span className="h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full bg-accent" aria-label="Unread" />}
        <span className="min-w-0 flex-1 text-[13px] font-medium text-fg">{e.title}</span>
        <span className="shrink-0 text-[11.5px] text-fg-3">{timeAgo(e.created_at)}</span>
      </span>
      {e.body && <span className="line-clamp-2 text-[12.5px] text-fg-2">{e.body}</span>}
    </>
  )
  const cls = cn('grid gap-0.5 rounded-lg px-2 py-2 text-left', e.link && 'hover:bg-surface-2')
  return <li>{e.link ? <Link to={e.link} onClick={onOpen} className={cls}>{inner}</Link> : <div className={cls}>{inner}</div>}</li>
}
