import { useAppStore } from '../store/appStore'
import { useTrending } from '../api/queries'
import { FeedCard } from '../components/FeedCard'
import { CardSkeleton } from '../components/CardSkeleton'
import { Alert } from '../components/shared/Alert'
import { Flame } from 'lucide-react'

export function TrendingPage() {
  const { currentCategory, viewMode } = useAppStore()
  const { data, status, error } = useTrending(currentCategory)

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="border-b border-border bg-card/50 p-6 flex flex-col items-center justify-center text-center">
        <Flame className="w-10 h-10 text-orange-500 mb-3" />
        <h1 className="text-2xl font-bold text-white tracking-tight">Trending Now</h1>
        <p className="text-textSecondary text-sm max-w-lg mt-2">
          Content gaining rapid velocity and cross-cluster attention over the last 24 hours.
        </p>
      </div>

      {data?.brief && (
        <div className="bg-gradient-to-r from-orange-900/30 to-red-900/20 border-b border-orange-500/20 p-6">
          <div className="max-w-4xl mx-auto">
            <h3 className="text-orange-400 text-sm font-semibold uppercase tracking-wider mb-2">Daily Brief: {data.brief.theme}</h3>
            <p className="text-orange-100/90 leading-relaxed text-sm">
              {data.brief.brief}
            </p>
          </div>
        </div>
      )}

      <div className="p-4 sm:p-6 lg:p-8 max-w-4xl mx-auto space-y-6">
        {status === 'pending' ? (
          <div className="space-y-6 flex flex-col items-stretch fade-in">
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </div>
        ) : status === 'error' ? (
          <Alert type="error" title="Error loading trending">
            {(error as Error).message}
          </Alert>
        ) : (
          <div className="space-y-6 flex flex-col items-stretch fade-in">
            {data?.items.length === 0 ? (
               <div className="text-center text-textSecondary py-12">
                 No trending items found for this category currently.
               </div>
            ) : (
              data?.items.map(item => (
                <FeedCard key={item.id} item={item} viewMode={viewMode} />
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}
