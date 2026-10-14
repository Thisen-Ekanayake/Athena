import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { useInbox, useInboxUnread, useMarkInboxSeen } from '../../api/queries/inbox'
import { Entry } from '../../features/inbox/InboxEntry'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'

/** New maps, updates to followed maps, what your follows caught, and digests. Opening it marks everything read. */
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
            <p className="px-2 py-3 text-[13px] text-fg-3">Nothing yet. Follow a map, search, source or cluster and its news shows up here.</p>
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
