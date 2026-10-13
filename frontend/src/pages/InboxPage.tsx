import { useEffect } from 'react'
import { Bell } from 'lucide-react'
import { useInbox, useMarkInboxSeen } from '../api/queries/inbox'
import { Entry } from '../components/layout/InboxBell'
import { EmptyState } from '../ui/EmptyState'
import { PageHeader } from '../ui/PageHeader'
import { Spinner } from '../ui/Spinner'

/** Everything from the last 60 days: map updates, new maps, new papers citing milestones. */
export function InboxPage() {
  const { data, isLoading } = useInbox(true, 200)
  const markSeen = useMarkInboxSeen()
  const unread = data?.unread ?? 0
  useEffect(() => {
    if (unread > 0) markSeen.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unread])
  return (
    <div className="mx-auto max-w-[760px]">
      <PageHeader title="Inbox" description="Map updates, new maps, and new papers that cite your maps' milestones, from the last 60 days." />
      {isLoading ? <Spinner /> : !data?.events.length ? (
        <EmptyState icon={Bell} title="Nothing yet">Map refreshes and new papers citing milestones show up here.</EmptyState>
      ) : (
        <ul className="grid gap-px rounded-xl border border-line bg-surface p-1.5">{data.events.map((e) => <Entry key={e.id} event={e} />)}</ul>
      )}
    </div>
  )
}
