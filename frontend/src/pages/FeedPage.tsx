import { useFeed } from '../api/queries'
import { useAppStore } from '../store/appStore'
import { FeedTopBar } from '../components/FeedTopBar'
import { FeedCard } from '../components/FeedCard'
import { CardSkeleton } from '../components/CardSkeleton'
import { Alert } from '../components/shared/Alert'
import { RelatedSidebar } from '../components/RelatedSidebar'
import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Flame, ArrowLeft, Database } from 'lucide-react'

export function FeedPage() {
  const { sourceId } = useParams()
  const [sort, setSort] = useState<'score' | 'date' | 'trending'>('score')
  const [dateRange, setDateRange] = useState<'24h' | '7d' | '30d' | 'all'>('all')
  const { currentCategory, setCategory, viewMode, setViewMode } = useAppStore()

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    status,
    error,
  } = useFeed(sort, currentCategory, dateRange, sourceId)

  // Implement simple infinite scroll observer
  useEffect(() => {
    let fetching = false
    const handleScroll = async () => {
      const { scrollTop, clientHeight, scrollHeight } = document.documentElement
      if (scrollHeight - scrollTop <= clientHeight * 1.5 && hasNextPage && !isFetchingNextPage && !fetching) {
        fetching = true
        await fetchNextPage()
        fetching = false
      }
    }
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  return (
    <div className="flex-1 relative">
      <FeedTopBar 
        sort={sort} setSort={setSort}
        category={currentCategory} setCategory={setCategory}
        dateRange={dateRange} setDateRange={setDateRange}
        viewMode={viewMode} setViewMode={setViewMode}
      />
      
      {sourceId && data?.pages[0]?.items[0] && (
        <div className="bg-zinc-900 border-b border-zinc-800 px-6 py-4 flex flex-col fade-in">
           <Link to="/" className="text-textSecondary hover:text-white text-sm flex items-center mb-2 w-fit">
             <ArrowLeft className="w-4 h-4 mr-1" /> Back to Main Feed
           </Link>
           <div className="flex items-center">
             <Database className="w-5 h-5 text-accentPrimary mr-2" />
             <h2 className="text-lg font-medium text-white">
               Source: {data.pages[0].items[0].source.name}
             </h2>
           </div>
        </div>
      )}

      {sourceId && data?.pages[0]?.items.length === 0 && status === 'success' && (
        <div className="bg-zinc-900 border-b border-zinc-800 px-6 py-4 flex flex-col fade-in">
           <Link to="/" className="text-textSecondary hover:text-white text-sm flex items-center mb-2 w-fit">
             <ArrowLeft className="w-4 h-4 mr-1" /> Back to Main Feed
           </Link>
           <h2 className="text-lg font-medium text-white">Viewing Unknown Source</h2>
        </div>
      )}
      
      {/* Hide trending banner if viewing a source, as trending sort doesn't really apply properly, though it can */}
      {sort === 'trending' && !sourceId && (
        <div className="bg-gradient-to-r from-purple-900/40 to-indigo-900/40 border-b border-purple-800/30 px-6 py-4 flex items-center justify-center fade-in">
           <Flame className="w-5 h-5 text-purple-400 mr-2" />
           <p className="text-sm font-medium text-purple-100">
             Trending Content: Items gaining sudden velocity and cross-cluster attention.
           </p>
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
          <Alert type="error" title="Error loading feed">
            {(error as Error).message}
          </Alert>
        ) : (
          <>
            {data?.pages.map((group, i) => (
              <div key={i} className="space-y-6 flex flex-col items-stretch fade-in">
                {group.items.map(item => (
                  <FeedCard key={item.id} item={item} viewMode={viewMode} />
                ))}
              </div>
            ))}
            
            {isFetchingNextPage && (
              <div className="flex justify-center p-6">
                <div className="w-6 h-6 rounded-full border-4 border-accentPrimary/20 border-t-accentPrimary animate-spin" />
              </div>
            )}
            
            {!hasNextPage && data?.pages[0]?.items.length > 0 && (
               <div className="text-center text-textSecondary text-sm py-12 opacity-50">
                 You've reached the end of the feed.
               </div>
            )}

            {data?.pages[0]?.items.length === 0 && (
               <div className="text-center text-textSecondary py-24">
                 <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-zinc-900 mb-4 border border-zinc-800">
                   <svg className="w-8 h-8 text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                     <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                   </svg>
                 </div>
                 <h3 className="text-lg font-medium text-white mb-2">No items found</h3>
                 <p className="max-w-sm mx-auto">There are currently no items matching this category or sort order.</p>
               </div>
            )}
          </>
        )}
      </div>

      {/* Render RelatedSidebar on top/alongside depending on its own CSS handling */}
      <RelatedSidebar />
    </div>
  )
}
