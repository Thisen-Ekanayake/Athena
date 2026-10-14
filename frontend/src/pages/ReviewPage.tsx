import { useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { ReviewView } from '../features/reviews/ReviewView'
import { ButtonLink } from '../ui/Button'

/** One literature review, full width. */
export function ReviewPage() {
  const { id } = useParams<{ id: string }>()
  return (
    <div className="mx-auto max-w-[860px]">
      <ButtonLink to="/library/reviews" variant="ghost" size="sm" className="mb-3 -ml-2.5"><ArrowLeft /> Reviews</ButtonLink>
      {id && <ReviewView id={id} />}
    </div>
  )
}
