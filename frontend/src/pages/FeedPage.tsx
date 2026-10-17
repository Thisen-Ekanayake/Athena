import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, EyeOff, Newspaper } from 'lucide-react'
import { useFeed, type FeedSort } from '../api/queries/feed'
import { useInterests } from '../api/queries/personal'
import { ItemList } from '../components/items/ItemRow'
import { useAppStore } from '../store/appStore'
import { Button, ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { Segmented } from '../ui/Segmented'
import { SkeletonRows } from '../ui/Skeleton'
import { Spinner } from '../ui/Spinner'
import { FollowButton } from '../features/inbox/FollowButton'
import { cn } from '../ui/cn'

type Sort = Extract<FeedSort, 'score' | 'date' | 'foryou'>
const SORT_KEY = 'athena.feed.sort'

/** The sort the viewer picked last on this browser, if any. */
function storedSort(): Sort | null {
  try {
    const v = localStorage.getItem(SORT_KEY)
    return v === 'score' || v === 'date' || v === 'foryou' ? v : null
  } catch {
    return null
  }
}
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
  const interests = useInterests()
  const [picked, setPicked] = useState<Sort | null>(storedSort)
  const [range, setRange] = useState<Range>('all')
  const [hideRead, setHideRead] = useState(false)
  const category = useAppStore((s) => s.currentCategory)
  const setCategory = useAppStore((s) => s.setCategory)
  const forYouOn = interests.data?.enabled !== false
  // For you is the default once there is enough to learn from; an explicit pick on this browser wins.
  const fallback: Sort = forYouOn && interests.data?.ready ? 'foryou' : 'score'
  const sort: Sort = picked === 'foryou' && !forYouOn ? 'score' : picked ?? fallback
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, status, error } = useFeed(sort, category, range, sourceId ?? null, 20, hideRead)
  const choose = (next: Sort) => {
    setPicked(next)
    try {
      localStorage.setItem(SORT_KEY, next)
    } catch {
      // Private windows: the pick lasts for this visit only.
    }
  }
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
  const learning = sort === 'foryou' && data?.pages[0]?.personalised === false
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
            {total !== undefined && (
              <span className="font-mono text-[12px] text-fg-3 tabular-nums" title={data?.pages[0]?.personalised ? 'For you ranks the best-scored items and the ones nearest your likes' : undefined}>
                {total.toLocaleString()} {data?.pages[0]?.personalised ? 'ranked for you' : 'items'}
              </span>
            )}
            {sourceId && <FollowButton target={{ kind: 'source', source_id: sourceId }} />}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Segmented label="Type" value={category ?? 'all'} options={CATEGORIES} onChange={(v) => setCategory(v === 'all' ? null : v)} />
        <Segmented label="Published within" value={range} options={RANGES} onChange={setRange} />
        <Button variant="ghost" size="sm" aria-pressed={hideRead} onClick={() => setHideRead((v) => !v)}
          title="Leave out what you marked read" className={cn(hideRead && 'bg-surface-2 text-fg')}>
          <EyeOff /> Hide read
        </Button>
        <Segmented
          label="Sort by"
          value={sort}
          options={[
            ...(forYouOn ? [{ value: 'foryou' as const, label: 'For you', title: 'Relevance blended with what you liked and saved' }] : []),
            { value: 'score' as const, label: 'Relevance' },
            { value: 'date' as const, label: 'Newest' },
          ]}
          onChange={choose}
          className="ml-auto"
        />
      </div>

      {learning && interests.data && (
        <Notice className="mb-4" title="For you is still learning">
          React with 👍 or 👎, or save items to a list, and this order starts to follow your interests
          ({Math.min(interests.data.signals, interests.data.full_at)} of {interests.data.full_at} so far). Until then it is the relevance order.
          {' '}<Link to="/settings/personalisation" className="underline">Personalisation settings</Link>
        </Notice>
      )}

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
