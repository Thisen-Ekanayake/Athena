import { useSearchParams } from 'react-router-dom'
import { useSearch } from '../api/queries/phase4'
import { FeedCard } from '../components/FeedCard'
import { Alert } from '../components/shared/Alert'
import { CardSkeleton } from '../components/CardSkeleton'
import { Search, Orbit } from 'lucide-react'
import { motion } from 'framer-motion'

export function SearchResultsPage() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const { data, isLoading, error } = useSearch(q, null, q.length > 2)

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      <div className="sticky top-0 z-20 glass-base border-b border-white/5 pt-28 pb-10 px-8 backdrop-blur-xl">
        <div className="max-w-[1200px] mx-auto">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-8 h-8 rounded-lg bg-accent-primary/10 border border-accent-primary/20 flex items-center justify-center text-accent-primary shadow-glow-primary">
              <Search className="w-4 h-4" />
            </div>
            <h1 className="text-3xl font-display font-bold text-white tracking-tight">
              Search <span className="text-accent-primary">Results</span>
            </h1>
          </div>
          <p className="text-sm text-text-muted font-medium max-w-2xl">
            Materializing intelligence patterns matching resonance query: <span className="text-white italic">"{q}"</span>
          </p>
        </div>
      </div>

      <motion.div 
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex-1 w-full max-w-[1200px] mx-auto px-6 py-12 md:px-12"
      >
        {q.length <= 2 ? (
          <div className="flex flex-col items-center justify-center py-32 text-center opacity-40">
            <Search className="w-10 h-10 text-text-ghost mb-4" />
            <h3 className="text-lg font-display font-medium text-white">Minimum Resonance Required</h3>
            <p className="text-sm text-text-muted mt-1">Please enter a longer query to synchronize search results.</p>
          </div>
        ) : isLoading ? (
          <div className="grid gap-6">
            {[1, 2, 3].map(i => <CardSkeleton key={i} />)}
          </div>
        ) : error ? (
          <Alert type="error" title="Search Failure">
            Materialization unsuccessful. The intelligence field could not be probed.
          </Alert>
        ) : data?.items?.length > 0 ? (
          <div className="grid gap-6">
            {data.items.map((item: any, idx: number) => (
              <FeedCard key={item.id} item={item} viewMode="expanded" index={idx} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-32 text-center opacity-40">
             <div className="w-20 h-20 rounded-full glass-void border border-white/5 flex items-center justify-center mb-6 shadow-inner">
               <Orbit className="w-10 h-10 text-text-ghost animate-pulse" />
             </div>
             <h3 className="text-xl font-display font-medium text-white mb-2">Zero Resonance</h3>
             <p className="max-w-xs text-sm text-text-muted">No intelligence matches your current parameter query. Try adjusting your semantic focus.</p>
          </div>
        )}
      </motion.div>
    </div>
  )
}

