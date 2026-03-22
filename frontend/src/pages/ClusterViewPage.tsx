import { useParams, Link } from 'react-router-dom'
import { useCluster } from '../api/queries/phase4'
import { FeedCard } from '../components/FeedCard'
import { CardSkeleton } from '../components/CardSkeleton'
import { Alert } from '../components/shared/Alert'
import { Layers, ArrowLeft } from 'lucide-react'

export function ClusterViewPage() {
  const { id } = useParams<{ id: string }>()
  const { data, isLoading, error } = useCluster(id!)

  return (
    <div className="flex-1 overflow-y-auto w-full">
      <div className="sticky top-0 z-10 bg-background/80 backdrop-blur-md border-b border-border px-6 py-4">
        <Link to="/settings/clusters" className="inline-flex items-center text-sm font-medium text-textSecondary hover:text-white transition-colors mb-2">
          <ArrowLeft className="w-4 h-4 mr-1" /> Back to Clusters
        </Link>
        <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight flex items-center gap-2">
          <Layers className="w-5 h-5 sm:w-6 sm:h-6 text-accentPrimary shrink-0" />
          {data ? data.cluster.label : 'Loading cluster...'}
        </h1>
        {data && data.cluster.summary && (
          <p className="text-sm text-textSecondary mt-2 max-w-3xl">{data.cluster.summary}</p>
        )}
      </div>

      <div className="p-4 sm:p-6 lg:p-8 max-w-4xl mx-auto space-y-6 fade-in">
        {isLoading ? (
          <div className="space-y-6">
            <CardSkeleton />
            <CardSkeleton />
          </div>
        ) : error ? (
          <Alert type="error" title="Error">Could not load this cluster.</Alert>
        ) : data?.items?.length > 0 ? (
          <div className="space-y-6 flex flex-col items-stretch">
            {data.items.map((item: any) => (
              <FeedCard key={item.id} item={item} viewMode="expanded" />
            ))}
          </div>
        ) : (
          <div className="text-center text-zinc-500 py-12">No items found in this cluster.</div>
        )}
      </div>
    </div>
  )
}
