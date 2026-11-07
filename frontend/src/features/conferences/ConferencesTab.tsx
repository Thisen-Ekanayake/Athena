import { Link } from 'react-router-dom'
import { Landmark } from 'lucide-react'
import { useConferences, type ConfProgress, type ConfStatus, type ConfVenue } from '../../api/queries/conferences'
import { apiErrorMessage } from '../../api/error'
import { useIsAdmin } from '../../api/queries/auth'
import { EmptyState } from '../../ui/EmptyState'
import { Notice } from '../../ui/Notice'
import { SkeletonRows } from '../../ui/Skeleton'
import { Sparkline } from '../../ui/Sparkline'
import { KIND_LABEL } from './format'

const STAGES: Partial<Record<NonNullable<ConfStatus['stage']>, string>> = {
  queued: 'Waiting for a worker', importing: 'Reading the ACL Anthology', terms: 'Working out rising terms',
  embedding: 'Sorting papers into topics', sorting: 'Sorting papers into the edited topics',
  summaries: 'Writing summaries', paused: 'Paused with the other background model work',
  waiting: 'Waiting for its turn on the GPU',
}

/** How far the first build has got, while it is going. Nothing once every paper is sorted and counted. */
export function PipelineProgress({ progress, status }: { progress: ConfProgress; status: ConfStatus }) {
  const busy = status.stage && status.stage !== 'idle' ? STAGES[status.stage] : null
  if (status.error) return <Notice tone="warn" title="The last conference sync stopped">{status.error}</Notice>
  if (!progress.papers || (progress.sorted >= progress.papers && progress.cited >= progress.papers && !busy)) return null
  const part = (n: number) => `${n.toLocaleString()} of ${progress.papers.toLocaleString()}`
  return (
    <Notice title={busy ?? 'Still sorting papers'}>
      Sorted into topics: {part(progress.sorted)}. With citation counts: {part(progress.cited)}. Topic shares and
      summaries fill in as this goes, newest papers first.
    </Notice>
  )
}

type CardVenue = Pick<ConfVenue, 'name' | 'full_name' | 'latest' | 'latest_papers' | 'latest_kinds' | 'editions' | 'papers'>

function VenueCard({ venue, to }: { venue: CardVenue; to: string }) {
  const kinds = Object.entries(venue.latest_kinds).map(([k, n]) => `${n?.toLocaleString()} ${KIND_LABEL[k as keyof typeof KIND_LABEL].toLowerCase()}`)
  return (
    <Link to={to} className="group grid min-w-0 gap-3 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-fg group-hover:text-accent-ink">{venue.name}</p>
          <p className="truncate text-[12px] text-fg-3" title={venue.full_name}>{venue.full_name}</p>
        </div>
        {venue.latest && <span className="shrink-0 font-mono text-[12px] text-fg-2">{venue.latest}</span>}
      </div>
      <div className="flex min-w-0 items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] text-fg">{venue.latest_papers.toLocaleString()} papers</p>
          {kinds.length > 0 && <p className="truncate text-[11.5px] text-fg-3">{kinds.join(' · ')}</p>}
        </div>
        <Sparkline values={venue.editions.slice(-14).map((e) => e.papers)} label={`${venue.name} papers per edition`} width={96} height={28} />
      </div>
      <p className="text-[11.5px] text-fg-3">{venue.editions.length} editions · {venue.papers.toLocaleString()} papers in all</p>
    </Link>
  )
}

/** Library → Conferences: the ACL family's venues, each opening its editions, topics and top papers. */
export function ConferencesTab() {
  const { data, isLoading, error } = useConferences()
  const isAdmin = useIsAdmin()
  if (isLoading) return <SkeletonRows count={4} />
  if (error) return <Notice tone="error">{apiErrorMessage(error, 'The conferences did not load.')}</Notice>
  if (!data || !data.progress.papers) {
    return (
      <EmptyState icon={Landmark} title="No conference papers yet">
        {isAdmin
          ? 'Read the ACL Anthology from Settings → Conferences. It also happens every Sunday.'
          : 'An admin can read the ACL Anthology from Settings → Conferences; it also happens every Sunday.'}
      </EmptyState>
    )
  }
  const venues = data.venues.filter((v) => v.papers > 0)
  const editions = data.family.editions
  const latest = editions[editions.length - 1]
  const family = {
    name: data.family.name, full_name: 'All of the venues below together', latest: latest?.year ?? null,
    latest_papers: latest?.papers ?? 0, latest_kinds: {}, papers: data.progress.papers, editions,
  }
  return (
    <div className="grid gap-4">
      <p className="text-[13px] text-fg-2">
        The ACL family's proceedings from the ACL Anthology, sorted into {data.topics.length} topics: what each
        edition was about, how topics moved over the years, award winners and the most cited papers. Shared by
        everyone.
      </p>
      <PipelineProgress progress={data.progress} status={data.status} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <VenueCard venue={family} to="/library/conferences/all" />
        {venues.map((v) => <VenueCard key={v.slug} venue={v} to={`/library/conferences/${v.slug}`} />)}
      </div>
    </div>
  )
}
