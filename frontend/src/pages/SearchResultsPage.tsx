import { useSearchParams } from 'react-router-dom'
import { useSearch } from '../api/queries/phase4'
import { FeedCard } from '../components/FeedCard'
import { Alert } from '../components/shared/Alert'
import { CardSkeleton } from '../components/CardSkeleton'
import { Search } from 'lucide-react'

export function SearchResultsPage() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') || ''
  const { data, isLoading, error } = useSearch(q, null, q.length > 2)

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="sticky top-0 z-10 bg-background/80 backdrop-blur-md border-b border-border px-6 py-4 flex items-center gap-3">
        <Search className="w-5 h-5 text-accentPrimary" />
        <h1 className="text-xl font-bold text-white tracking-tight">
          Search Results for "{q}"
        </h1>
      </div>

      <div className="p-4 sm:p-6 lg:p-8 max-w-4xl mx-auto space-y-6 fade-in">
        {q.length <= 2 ? (
          <div className="text-center text-zinc-500 py-12">
            Please enter a longer query to search.
          </div>
        ) : isLoading ? (
          <div className="space-y-6">
            <CardSkeleton />
            <CardSkeleton />
            <CardSkeleton />
          </div>
        ) : error ? (
          <Alert type="error" title="Search failed">
            Could not retrieve search results. Please try again.
          </Alert>
        ) : data?.items?.length > 0 ? (
          <div className="space-y-6 flex flex-col items-stretch">
            {data.items.map((item: any) => (
              <FeedCard key={item.id} item={item} viewMode="expanded" />
            ))}
          </div>
        ) : (
          <div className="text-center text-textSecondary py-24">
             <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-zinc-900 mb-4 border border-zinc-800">
               <Search className="w-8 h-8 text-zinc-600" />
             </div>
             <h3 className="text-lg font-medium text-white mb-2">No results found</h3>
             <p className="max-w-sm mx-auto">Try adjusting your search query or using different semantic concepts.</p>
          </div>
        )}
      </div>
    </div>
  )
}
