import { useScoreBreakdown } from '../api/queries/phase4'
import { formatDistanceToNow } from 'date-fns'
import { Flame } from 'lucide-react'
import { motion } from 'framer-motion'

interface ScoreTooltipProps {
  itemId: string
  score: number
  isTrending?: boolean
}

export function ScoreTooltip({ itemId, score, isTrending }: ScoreTooltipProps) {
  const { data, isLoading, error } = useScoreBreakdown(itemId, true)

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95, y: 4 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: 4 }}
      transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
      className="absolute z-50 bottom-full left-0 mb-3 w-64 glass-float p-0 overflow-hidden transform-gpu"
    >
      <div className="px-4 py-3 border-b border-border-subtle bg-white/5 flex justify-between items-center">
        <span className="text-xs font-display font-semibold text-text-primary tracking-wide">RELEVANCE BREAKDOWN</span>
        <span className="font-mono text-sm font-bold text-accent-primary">{(score * 100).toFixed(0)}</span>
      </div>
      
      <div className="p-4 space-y-4">
        {isLoading ? (
          <div className="space-y-4">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="space-y-1.5 opacity-50">
                <div className="h-2 bg-white/10 rounded w-20"></div>
                <div className="h-1 bg-white/5 rounded w-full"></div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="text-accent-critical text-[11px] text-center py-2">Signal unavailable</div>
        ) : data ? (
          <>
            <div className="space-y-4">
              {data.signals.map((s, idx) => {
                const pct = (s.value / s.max_value) * 100;
                return (
                  <div key={idx} className="space-y-1.5">
                    <div className="flex justify-between items-center text-[10px] uppercase tracking-wider font-medium text-text-muted">
                      <span>{s.label}</span>
                      <span className="font-mono">{pct.toFixed(0)}%</span>
                    </div>
                    <div className="h-1 w-full bg-void/50 rounded-full overflow-hidden border border-white/5">
                      <motion.div 
                        initial={{ width: 0 }}
                        animate={{ width: `${pct}%` }}
                        transition={{ duration: 0.6, delay: 0.1 + idx * 0.05 }}
                        className="h-full bg-accent-primary rounded-full" 
                      />
                    </div>
                  </div>
                )
              })}
            </div>
            
            <div className="pt-3 mt-1 border-t border-border-subtle flex items-center justify-between text-[10px] text-text-ghost font-medium">
               {isTrending && (
                 <span className="flex items-center gap-1 text-accent-tertiary">
                   <Flame className="w-2.5 h-2.5" /> Trending Citations
                 </span>
               )}
               <span className="ml-auto">Synced {formatDistanceToNow(new Date(data.computed_at))} ago</span>
            </div>
          </>
        ) : null}
      </div>
    </motion.div>
  )
}

