import { useParams, Link } from 'react-router-dom'
import { useCluster } from '../api/queries/phase4'
import { FeedCard } from '../components/FeedCard'
import { CardSkeleton } from '../components/CardSkeleton'
import { Alert } from '../components/shared/Alert'
import { Layers, ArrowLeft, Sparkles, Orbit } from 'lucide-react'


export function ClusterViewPage() {
  const { id } = useParams<{ id: string }>()
  const { data, isLoading, error } = useCluster(id!)

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      {/* Header Area */}
      <div className="sticky top-0 z-20 glass-base border-b border-white/5 pt-28 pb-10 px-8 backdrop-blur-xl">
        <div className="max-w-[1200px] mx-auto">
          <Link to="/" className="inline-flex items-center text-[11px] font-bold tracking-widest text-text-ghost hover:text-white transition-all mb-4 uppercase">
            <ArrowLeft className="w-3.5 h-3.5 mr-1.5" /> Back to Dashboard
          </Link>
          
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-8 h-8 rounded-lg bg-accent-secondary/10 border border-accent-secondary/20 flex items-center justify-center text-accent-secondary shadow-glow-secondary">
                  <Layers className="w-4 h-4" />
                </div>
                <h1 className="text-3xl font-display font-bold text-white tracking-tight truncate">
                  {data ? data.cluster.label : 'Analyzing Node...'}
                </h1>
              </div>
              {data && data.cluster.summary && (
                <p className="text-sm text-text-secondary max-w-3xl leading-relaxed mt-4 p-4 rounded-xl glass-void border border-white/5">
                  <Sparkles className="w-4 h-4 text-accent-tertiary inline mr-2 mb-1" />
                  {data.cluster.summary}
                </p>
              )}
            </div>
            
            {data && (
              <div className="flex flex-col items-start md:items-end gap-1">
                <span className="text-[10px] font-display font-bold tracking-[0.2em] text-text-ghost uppercase">Intelligence Mass</span>
                <span className="font-mono text-2xl font-bold text-accent-secondary">{data.items.length} Elements</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 w-full max-w-[1200px] mx-auto px-6 py-12 md:px-12">
        <div className="space-y-6">
          {isLoading ? (
            <div className="grid gap-6">
              {[1, 2].map(i => <CardSkeleton key={i} />)}
            </div>
          ) : error ? (
            <Alert type="error" title="Node Fragmentation">Could not materialize cluster resonance.</Alert>
          ) : data?.items?.length > 0 ? (
            <div className="grid gap-6">
              {data.items.map((item: any, idx: number) => (
                <FeedCard key={item.id} item={item} viewMode="expanded" index={idx} />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-32 text-center opacity-40">
              <Orbit className="w-12 h-12 text-text-ghost mb-4 animate-pulse" />
              <h3 className="text-xl font-display font-medium text-white mb-2">Silent Silo</h3>
              <p className="text-sm text-text-muted">No intelligence found within this localized structure.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

