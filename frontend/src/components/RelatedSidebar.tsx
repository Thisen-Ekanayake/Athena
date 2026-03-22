import { X } from 'lucide-react'
import { useAppStore } from '../store/appStore'
import { useRelatedItems } from '../api/queries/related'
import { FeedCard } from './FeedCard'

export function RelatedSidebar() {
  const { relatedItemId, setRelatedItemId } = useAppStore()
  const { data: relatedItems, isLoading, error } = useRelatedItems(relatedItemId)

  if (!relatedItemId) return null

  return (
    <>
      <div 
        className="fixed inset-0 bg-black/50 z-30 md:hidden"
        onClick={() => setRelatedItemId(null)}
      />
      
      <aside className="fixed inset-y-0 right-0 z-40 w-full md:w-96 bg-card border-l border-border shadow-2xl flex flex-col transform transition-transform duration-300 translate-x-0 slide-in-from-right fade-in">
        <div className="flex items-center justify-between px-4 py-4 border-b border-border bg-background/50">
          <h2 className="text-lg font-bold text-white tracking-tight">Related Articles</h2>
          <button 
            onClick={() => setRelatedItemId(null)}
            className="p-1.5 rounded-md text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoading ? (
            <div className="space-y-4">
               {[1, 2, 3].map(i => (
                 <div key={i} className="card p-4 animate-pulse">
                   <div className="h-4 bg-zinc-800 rounded w-3/4 mb-2"></div>
                   <div className="h-3 bg-zinc-800 rounded w-1/2"></div>
                 </div>
               ))}
            </div>
          ) : error ? (
            <div className="text-center text-red-400 py-8 text-sm">Failed to load related items</div>
          ) : relatedItems && relatedItems.length > 0 ? (
            <div className="space-y-4 flex flex-col items-stretch">
              {relatedItems.map((item: any) => (
                <FeedCard key={item.id} item={item} viewMode="compact" />
              ))}
            </div>
          ) : (
            <div className="text-center text-zinc-500 py-8 text-sm">No related articles found.</div>
          )}
        </div>
      </aside>
    </>
  )
}
