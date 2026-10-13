import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bell, Settings } from 'lucide-react'
import { useInbox, useMarkInboxSeen } from '../api/queries/inbox'
import { Entry } from '../features/inbox/InboxEntry'
import { ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { PageHeader } from '../ui/PageHeader'
import { Spinner } from '../ui/Spinner'

/** Everything from the last 60 days. `?open=<id>` opens one entry's papers or digest. */
export function InboxPage() {
  const { data, isLoading } = useInbox(true, 200)
  const markSeen = useMarkInboxSeen()
  const [params] = useSearchParams()
  const [open, setOpen] = useState<Set<string>>(() => new Set(params.get('open') ? [params.get('open')!] : []))
  const unread = data?.unread ?? 0
  useEffect(() => {
    if (unread > 0) markSeen.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unread])

  // The bell links here with ?open=<id>: open that entry and bring it into view once the list is in.
  const target = params.get('open')
  useEffect(() => {
    if (!target || !data) return
    setOpen((s) => new Set(s).add(target))
    document.getElementById(`inbox-${target}`)?.scrollIntoView({ block: 'start' })
  }, [target, data])

  const toggle = (id: string) => setOpen((s) => {
    const next = new Set(s)
    if (!next.delete(id)) next.add(id)
    return next
  })

  return (
    <div className="mx-auto max-w-[760px]">
      <PageHeader
        title="Inbox"
        description="New maps, updates to the maps you follow, what your searches, sources and clusters caught, and your digests, from the last 60 days."
        actions={<ButtonLink to="/settings/notifications" variant="ghost" size="sm"><Settings /> Notifications</ButtonLink>}
      />
      {isLoading ? <Spinner /> : !data?.events.length ? (
        <EmptyState icon={Bell} title="Nothing yet">Follow a map, a search, a source or a cluster, and its news shows up here.</EmptyState>
      ) : (
        <ul className="grid gap-px rounded-xl border border-line bg-surface p-1.5">
          {data.events.map((e) => <Entry key={e.id} event={e} open={open.has(e.id)} onToggle={() => toggle(e.id)} />)}
        </ul>
      )}
    </div>
  )
}
