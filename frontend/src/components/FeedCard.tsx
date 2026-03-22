import type { FeedItem } from '../api/client'
import { formatDistanceToNow } from 'date-fns'
import { Flame, Star, Layers, Search, ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

interface FeedCardProps {
  item: FeedItem
  viewMode?: 'compact' | 'expanded'
}

export function FeedCard({ item, viewMode = 'expanded' }: FeedCardProps) {
  const [expanded, setExpanded] = useState(false)
  
  const scoreColor = 
    item.score >= 0.8 ? 'text-scoreHigh' : 
    item.score >= 0.5 ? 'text-scoreMid' : 'text-scoreLow'

  return (
    <article className="card card-hover p-5 flex flex-col gap-3 group animate-in flex-col opacity-100 fade-in slide-in-from-bottom-4 duration-500 ease-out fill-mode-forwards">
      {/* Header Info */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2 flex-wrap text-sm">
          <span className="font-medium text-textSecondary hover:text-white transition-colors cursor-pointer">
            {item.source.name}
          </span>
          <span className="text-zinc-600">•</span>
          <span className="text-zinc-400" title={new Date(item.published_at).toLocaleString()}>
            {formatDistanceToNow(new Date(item.published_at), { addSuffix: true })}
          </span>
          
          {/* Badges */}
          <div className="flex gap-2 ml-2">
            {item.is_trending && (
               <span className="badge badge-purple flex items-center gap-1">
                 <Flame className="w-3 h-3" /> Trending
               </span>
            )}
            {item.category === 'paper' && (
              <span className="badge badge-blue">Paper</span>
            )}
          </div>
        </div>

        {/* Score Ring */}
        <div className={`flex items-center gap-1.5 font-bold ${scoreColor} bg-zinc-900 px-2 py-1 rounded-md border border-zinc-800`}>
          <Star className="w-4 h-4 fill-current" />
          {(item.score * 100).toFixed(0)}
        </div>
      </div>

      {/* Main Title */}
      <h2 className="text-xl font-bold text-textPrimary leading-snug group-hover:text-accentPrimary transition-colors">
        <a href={item.url} target="_blank" rel="noopener noreferrer">
          {item.title}
        </a>
      </h2>

      {/* Summary */}
      {viewMode === 'expanded' && item.summary && (
        <p className="text-textSecondary leading-relaxed text-sm">
          {item.summary}
        </p>
      )}

      {/* Expandable Takeaways (if present and not compact mode) */}
      {viewMode === 'expanded' && item.takeaways && item.takeaways.length > 0 && (
        <div className="mt-2">
          <button 
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs font-medium text-accentPrimary hover:text-accentHover transition-colors"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            {expanded ? 'Hide Key Takeaways' : `${item.takeaways.length} Key Takeaways`}
          </button>
          
          {expanded && (
            <ul className="mt-3 space-y-2 text-sm text-zinc-300 bg-zinc-900/50 p-4 rounded-md border border-zinc-800/50">
              {item.takeaways.map((t, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="text-accentPrimary mt-0.5">•</span>
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Footer Info (Clusters / Related Context) */}
      <div className="mt-2 pt-4 border-t border-border/50 flex items-center justify-between text-xs text-zinc-500 font-medium">
        <div className="flex items-center gap-4">
          {item.cluster && (
            <div className="flex items-center gap-1.5 hover:text-zinc-300 cursor-pointer transition-colors">
              <Layers className="w-4 h-4" />
              {item.cluster.label}
              {item.cluster.item_count > 1 && (
                <span className="bg-zinc-800 text-zinc-400 px-1.5 rounded-sm">{item.cluster.item_count}</span>
              )}
            </div>
          )}
        </div>
        
        {item.related_count > 0 && (
          <div className="flex items-center gap-1.5 hover:text-zinc-300 cursor-pointer transition-colors">
            <Search className="w-4 h-4" />
            {item.related_count} related
          </div>
        )}
      </div>
    </article>
  )
}
