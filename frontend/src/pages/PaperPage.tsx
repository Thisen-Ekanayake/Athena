import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { useItemDetail } from '../api/queries/feed'
import { PaperDetail } from '../components/paper/PaperDetail'
import { SaveMenu } from '../components/items/SaveMenu'
import { Button } from '../ui/Button'
import { buttonClass } from '../ui/buttonClass'

/** One item as a full page, for longer reading. The side panel's "expand" button leads here. */
export function PaperPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data } = useItemDetail(id!, true)

  return (
    <div className="mx-auto max-w-[760px]">
      <div className="mb-2 flex items-center gap-1">
        <Button variant="ghost" size="sm" className="-ml-2.5 mr-auto" onClick={() => navigate(-1)}><ArrowLeft /> Back</Button>
        <SaveMenu itemId={id!} size="icon" />
        {data?.url && (
          <a href={data.url} target="_blank" rel="noopener noreferrer" className={buttonClass('secondary', 'sm')}>
            Open the original <ExternalLink />
          </a>
        )}
      </div>
      <PaperDetail itemId={id!} layout="page" />
    </div>
  )
}
