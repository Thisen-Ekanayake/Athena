import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ArrowLeft, Layers } from 'lucide-react'
import { useCluster } from '../api/queries/clusters'
import { ItemList } from '../components/items/ItemRow'
import { FollowButton } from '../features/inbox/FollowButton'
import { Button, ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { SkeletonRows } from '../ui/Skeleton'

export function ClusterPage() {
  const { id } = useParams<{ id: string }>()
  // Keyed on the id, so moving to another cluster starts again at page 1.
  return <ClusterView key={id} id={id!} />
}

function ClusterView({ id }: { id: string }) {
  const [page, setPage] = useState(1)
  const { data, isLoading, error } = useCluster(id, page)

  return (
    <div className="mx-auto max-w-[920px]">
      <ButtonLink to="/clusters" variant="ghost" size="sm" className="mb-3 -ml-2.5"><ArrowLeft /> Clusters</ButtonLink>
      <PageHeader
        title={data?.cluster.label || (isLoading ? 'Loading…' : 'Cluster')}
        description={data?.cluster.summary}
        actions={data && (
          <>
            <span className="font-mono text-[12px] text-fg-3 tabular-nums">{data.pagination.total} items</span>
            <FollowButton target={{ kind: 'cluster', cluster_id: id }} />
          </>
        )}
      />
      {isLoading ? (
        <SkeletonRows count={5} />
      ) : error || !data ? (
        <Notice tone="error" title="This cluster could not be loaded">It may have been regrouped since you opened it.</Notice>
      ) : data.items.length === 0 ? (
        <EmptyState icon={Layers} title="This cluster is empty" />
      ) : (
        <>
          <ItemList items={data.items} />
          {(page > 1 || data.pagination.has_next) && (
            <div className="mt-4 flex items-center justify-between">
              <Button variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <span className="font-mono text-[12px] text-fg-3">Page {page}</span>
              <Button variant="secondary" size="sm" disabled={!data.pagination.has_next} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
