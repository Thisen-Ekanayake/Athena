import { Link } from 'react-router-dom'
import { Layers } from 'lucide-react'
import { useClusters } from '../api/queries/clusters'
import { useAppStore } from '../store/appStore'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { Skeleton } from '../ui/Skeleton'

/** Themes found automatically by grouping similar items in the library. */
export function ClustersPage() {
  const category = useAppStore((s) => s.currentCategory)
  const { data: clusters, isLoading, error } = useClusters(category)

  return (
    <div className="mx-auto max-w-[1100px]">
      <PageHeader
        title="Clusters"
        description="Themes Athena found on its own by grouping similar items in your library. They change as new items arrive."
        actions={clusters && <span className="font-mono text-[12px] text-fg-3 tabular-nums">{clusters.length} clusters</span>}
      />
      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-36 rounded-xl" />)}
        </div>
      ) : error ? (
        <Notice tone="error" title="Clusters could not be loaded">Check that the API is running.</Notice>
      ) : !clusters?.length ? (
        <EmptyState icon={Layers} title="No clusters yet">Clusters form automatically once enough items have been fetched and embedded.</EmptyState>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {clusters.map((c) => (
            <Link key={c.id} to={`/clusters/${c.id}`} className="group flex flex-col gap-2 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-surface-2/50">
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-[14.5px] font-medium leading-snug text-fg">{c.label || 'Unnamed cluster'}</h2>
                <span className="shrink-0 font-mono text-[12px] text-fg-3 tabular-nums">{c.item_count}</span>
              </div>
              {c.summary && <p className="line-clamp-3 text-[13px] leading-relaxed text-fg-2">{c.summary}</p>}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
