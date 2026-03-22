import { useFeed } from '../api/queries'
import { useAppStore } from '../store/appStore'
import { FeedTopBar } from '../components/FeedTopBar'
import { FeedCard } from '../components/FeedCard'
import { Alert } from '../components/shared/Alert'
import { useState, useEffect } from 'react'

export function FeedPage() {
  const [sort, setSort] = useState<'score' | 'date' | 'trending'>('score')
  const { currentCategory, setCategory, viewMode, setViewMode } = useAppStore()

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    status,
    error,
  } = useFeed(sort, currentCategory)

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
        viewMode={viewMode} setViewMode={setViewMode}
      />
      
      <div className="p-4 sm:p-6 lg:p-8 max-w-4xl mx-auto space-y-6">
        {status === 'pending' ? (
          <div className="flex justify-center p-12">
            <div className="w-8 h-8 rounded-full border-4 border-accentPrimary/20 border-t-accentPrimary animate-spin" />
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
    </div>
  )
}
