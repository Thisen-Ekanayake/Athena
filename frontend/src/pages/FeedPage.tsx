import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ArrowLeft, Newspaper } from 'lucide-react'
import { useFeed } from '../api/queries'
import { ItemList } from '../components/items/ItemRow'
import { useAppStore } from '../store/appStore'
import { ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { Segmented } from '../ui/Segmented'
import { SkeletonRows } from '../ui/Skeleton'
import { Spinner } from '../ui/Spinner'
import { FollowButton } from '../features/inbox/FollowButton'

type Sort = 'score' | 'date'
type Range = '24h' | '7d' | '30d' | 'all'

const CATEGORIES = [
  { value: 'all', label: 'All' },
  { value: 'paper', label: 'Papers' },
  { value: 'company_blog', label: 'Lab blogs' },
  { value: 'community_blog', label: 'Community' },
]

const RANGES: { value: Range; label: string }[] = [
  { value: '24h', label: 'Day' },
  { value: '7d', label: 'Week' },
  { value: '30d', label: 'Month' },
  { value: 'all', label: 'All time' },
]

/** Everything from your sources, ranked. `/sources/:sourceId` shows one source. */
export function FeedPage() {
  const { sourceId } = useParams()
  const [sort, setSort] = useState<Sort>('score')
  const [range, setRange] = useState<Range>('all')
  const category = useAppStore((s) => s.currentCategory)
  const setCategory = useAppStore((s) => s.setCategory)
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, status, error } = useFeed(sort, category, range, sourceId ?? null)
  const sentinel = useRef<HTMLDivElement>(null)

  // Load the next page when the bottom of the list scrolls into view.
  useEffect(() => {
    const el = sentinel.current
    if (!el || !hasNextPage) return
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !isFetchingNextPage) fetchNextPage()
    }, { rootMargin: '600px' })
    io.observe(el)
    return () => io.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  const items = data?.pages.flatMap((p) => p.items) ?? []
  const total = data?.pages[0]?.pagination.total
  const sourceName = sourceId ? items[0]?.source.name : null

  return (
    <div className="mx-auto max-w-[920px]">
      {sourceId && (
        <ButtonLink to="/feed" variant="ghost" size="sm" className="mb-3 -ml-2.5"><ArrowLeft /> All sources</ButtonLink>
      )}
      <PageHeader
        title={sourceId ? sourceName ?? 'Source' : 'Feed'}
        description={sourceId ? 'Everything fetched from this source, ranked.' : 'Everything new from your sources, ranked by relevance.'}
        actions={
          <>
            {total !== undefined && <span className="font-mono text-[12px] text-fg-3 tabular-nums">{total.toLocaleString()} items</span>}
            {sourceId && <FollowButton target={{ kind: 'source', source_id: sourceId }} />}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented label="Type" value={category ?? 'all'} options={CATEGORIES} onChange={(v) => setCategory(v === 'all' ? null : v)} />
        <Segmented label="Published within" value={range} options={RANGES} onChange={setRange} />
        <Segmented
          label="Sort by"
          value={sort}
          options={[{ value: 'score', label: 'Relevance' }, { value: 'date', label: 'Newest' }]}
          onChange={setSort}
          className="ml-auto"
        />
      </div>

      {status === 'pending' ? (
        <SkeletonRows count={6} />
      ) : status === 'error' ? (
        <Notice tone="error" title="The feed could not be loaded">{error?.message}. Check that the API is running.</Notice>
      ) : items.length === 0 ? (
        <EmptyState icon={Newspaper} title="Nothing here yet">
          {range === 'all' && !category ? 'Sync your sources to fetch the first items.' : 'Try a wider date range or another type.'}
        </EmptyState>
      ) : (
        <>
          <ItemList items={items} />
          <div ref={sentinel} className="flex justify-center py-6">
            {isFetchingNextPage ? <Spinner label="Loading more…" /> : !hasNextPage && <span className="text-[12px] text-fg-3">That's everything.</span>}
          </div>
        </>
      )}
    </div>
  )
}
