import { useClusters } from '../api/queries'
import { useAppStore } from '../store/appStore'
import { Layers, ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Alert } from '../components/shared/Alert'

export function ClusterBrowserPage() {
  const { currentCategory } = useAppStore()
  const { data: clusters, isLoading, error } = useClusters(currentCategory)

  return (
    <div className="flex-1 overflow-y-auto w-full">
      <div className="sticky top-0 z-10 bg-background/80 backdrop-blur-md border-b border-border px-6 py-4">
        <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
          <Layers className="w-6 h-6 text-accentPrimary" />
          Topic Clusters
        </h1>
        <p className="text-sm text-textSecondary mt-1">Explore dynamically generated topics across all sources.</p>
      </div>

      <div className="p-4 sm:p-6 lg:p-8 max-w-6xl mx-auto space-y-6 fade-in">
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} className="card p-5 animate-pulse h-32 bg-zinc-900 border-zinc-800"></div>
            ))}
          </div>
        ) : error ? (
          <Alert type="error" title="Error loading clusters">Failed to fetch topic clusters.</Alert>
        ) : clusters && clusters.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {clusters.map((cluster) => (
              <Link key={cluster.id} to={`/clusters/${cluster.id}`} className="card card-hover p-5 flex flex-col group bg-zinc-900 hover:bg-zinc-800/80 transition-all border-zinc-800">
                <div className="flex justify-between items-start mb-3">
                  <h3 className="font-bold text-lg text-white group-hover:text-accentPrimary transition-colors line-clamp-2">
                    {cluster.label}
                  </h3>
                  <span className="bg-zinc-800 text-zinc-300 text-xs font-semibold px-2 py-1 rounded-full whitespace-nowrap">
                    {cluster.item_count} items
                  </span>
                </div>
                {cluster.summary && (
                  <p className="text-sm text-zinc-500 line-clamp-2 flex-grow">
                    {cluster.summary}
                  </p>
                )}
                <div className="mt-4 flex items-center text-xs font-semibold text-accentPrimary opacity-0 group-hover:opacity-100 transition-opacity">
                  View cluster <ArrowRight className="w-3 h-3 ml-1" />
                </div>
              </Link>
            ))}
          </div>
        ) : (
           <div className="text-center text-zinc-500 py-24">No active clusters available in this category.</div>
        )}
      </div>
    </div>
  )
}
