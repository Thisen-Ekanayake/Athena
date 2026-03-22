
import { useScoreBreakdown } from '../api/queries/phase4'
import { formatDistanceToNow } from 'date-fns'
import { Flame } from 'lucide-react'

interface ScoreTooltipProps {
  itemId: string
  score: number
  isTrending?: boolean
}

export function ScoreTooltip({ itemId, score, isTrending }: ScoreTooltipProps) {
  const { data, isLoading, error } = useScoreBreakdown(itemId, true)

  return (
    <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl overflow-hidden p-0 text-sm animate-in fade-in zoom-in-95 duration-150">
      <div className="bg-zinc-800/50 px-4 py-3 border-b border-zinc-800 flex justify-between items-center">
        <span className="font-semibold text-white">Relevance Score</span>
        <span className="font-bold text-accentPrimary">{(score * 100).toFixed(0)}</span>
      </div>
      
      <div className="p-4 space-y-3">
        {isLoading ? (
          <div className="space-y-3 animate-pulse">
            {[1, 2, 3, 4, 5].map(i => (
              <div key={i} className="flex justify-between items-center">
                <div className="h-3 bg-zinc-800 rounded w-24"></div>
                <div className="h-2 bg-zinc-800 rounded w-16"></div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="text-red-400 text-xs text-center">Failed to load breakdown</div>
        ) : data ? (
          <>
            {data.signals.map((s, idx) => {
              const pct = (s.value / s.max_value) * 100;
              return (
                <div key={idx} className="space-y-1">
                   <div className="flex justify-between text-xs text-zinc-400">
                     <span>{s.label}</span>
                     <span>{pct.toFixed(0)}%</span>
                   </div>
                   <div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
                     <div 
                        className="h-full bg-accentPrimary rounded-full" 
                        style={{ width: `${pct}%` }} 
                     />
                   </div>
                </div>
              )
            })}
            
            <div className="pt-3 mt-3 border-t border-zinc-800/80 flex items-center justify-between text-xs text-zinc-500">
               {isTrending && (
                 <span className="flex items-center gap-1 text-purple-400">
                   <Flame className="w-3 h-3" /> Trending
                 </span>
               )}
               <span>Computed {formatDistanceToNow(new Date(data.computed_at))} ago</span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}
