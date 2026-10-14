import { Link } from 'react-router-dom'
import { FileText, Trash2 } from 'lucide-react'
import { isWriting, useDeleteReview, useReviews } from '../../api/queries/reviews'
import { timeAgo } from '../../components/items/format'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { EmptyState } from '../../ui/EmptyState'
import { SkeletonRows } from '../../ui/Skeleton'
import { ReviewSourceChip } from './ReviewView'

/** Your literature reviews, newest first. */
export function ReviewsTab() {
  const { data, isLoading } = useReviews()
  const remove = useDeleteReview()
  if (isLoading) return <SkeletonRows count={3} />
  if (!data?.length) {
    return (
      <EmptyState icon={FileText} title="No reviews yet">
        Write one from a research map (“Write a review” on its page) or from the search page. Reviews from a map read its
        papers' own text and cite them.
      </EmptyState>
    )
  }
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
      {data.map((r) => (
        <li key={r.id} className="group flex items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <Link to={`/reviews/${r.id}`} className="block truncate text-[13.5px] font-medium text-fg hover:underline">{r.title}</Link>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-fg-3">
              <ReviewSourceChip review={r} />
              {isWriting(r) ? <Chip>{r.progress.label ?? 'Writing'}…</Chip>
                : r.status === 'failed' ? <Chip tone="bad">Not finished</Chip>
                  : <span>{r.cited} papers cited</span>}
              <span>{timeAgo(r.created_at ?? '')}</span>
            </div>
          </div>
          <Button variant="ghost" size="icon-sm" title="Delete" aria-label={`Delete ${r.title}`} disabled={isWriting(r)}
            onClick={() => remove.mutate(r.id)} className="opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 max-md:opacity-100">
            <Trash2 />
          </Button>
        </li>
      ))}
    </ul>
  )
}
