import { useNavigate } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { useStartReview } from '../../api/queries/reviews'
import { Button } from '../../ui/Button'

/** Starts a literature review grounded in this map, and opens it. */
export function WriteReviewButton({ slug }: { slug: string }) {
  const start = useStartReview()
  const navigate = useNavigate()
  return (
    <span className="inline-flex items-center gap-2">
      <Button variant="ai" size="sm" disabled={start.isPending}
        title="A literature review from this map: how the field developed, its main approaches, open problems and where to start, citing the papers' own text. Takes a few minutes."
        onClick={() => start.mutate({ topic_slug: slug }, { onSuccess: (r) => navigate(`/reviews/${r.id}`) })}>
        <Sparkles /> {start.isPending ? 'Starting…' : 'Write a review'}
      </Button>
      {start.error && <span role="alert" className="max-w-[260px] text-[12px] text-bad">{apiErrorMessage(start.error, 'Could not start the review')}</span>}
    </span>
  )
}
