import { X, Sparkles, Orbit, Network } from 'lucide-react'
import { useAppStore } from '../store/appStore'
import { useRelatedItems } from '../api/queries/related'
import { FeedCard } from './FeedCard'
import { motion, AnimatePresence } from 'framer-motion'

export function RelatedSidebar() {
  const { relatedItemId, setRelatedItemId } = useAppStore()
  const { data: relatedItems, isLoading, error } = useRelatedItems(relatedItemId)

  return (
    <AnimatePresence>
      {relatedItemId && (
        <>
          {/* Overlay for mobile/tablet */}
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-void/60 backdrop-blur-md z-40 lg:hidden"
            onClick={() => setRelatedItemId(null)}
          />
          
          <motion.aside 
            initial={{ x: '100%', opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-y-0 right-0 z-50 w-full md:w-[400px] glass-opaque backdrop-blur-3xl border-l border-white/10 shadow-2xl flex flex-col"
          >
            {/* Header */}
            <div className="relative overflow-hidden px-8 py-8 border-b border-white/5 bg-accent-primary/5">
              <div className="absolute top-0 right-0 p-4 opacity-5">
                <Network className="w-32 h-32 text-accent-primary" />
              </div>
              
              <div className="relative z-10 flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-display font-bold text-white tracking-tight flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-accent-primary" />
                    Related <span className="text-accent-primary">Signals</span>
                  </h2>
                  <p className="text-[10px] font-display font-bold text-text-ghost uppercase tracking-[0.2em] mt-1">Cross-Resonant Intelligence</p>
                </div>
                <button 
                  onClick={() => setRelatedItemId(null)}
                  className="w-10 h-10 rounded-full glass-void border border-white/10 flex items-center justify-center text-text-muted hover:text-white hover:border-white/20 transition-all group"
                >
                  <X className="w-5 h-5 group-hover:rotate-90 transition-transform duration-300" />
                </button>
              </div>
            </div>
            
            {/* Content area */}
            <div className="flex-1 overflow-y-auto px-6 py-8 space-y-6 no-scrollbar">
              {isLoading ? (
                <div className="space-y-6">
                   {[1, 2, 3].map(i => (
                     <div key={i} className="glass-void rounded-xl p-6 h-40 animate-pulse border border-white/5" />
                   ))}
                </div>
              ) : error ? (
                <div className="glass-void border border-accent-secondary/20 p-8 rounded-2xl text-center">
                  <Orbit className="w-10 h-10 text-accent-secondary mx-auto mb-4 animate-spin-slow" />
                  <p className="text-white font-display font-bold text-sm uppercase tracking-widest leading-relaxed">Resonance Lost</p>
                  <p className="text-text-muted text-xs mt-2">Failed to materialize related intelligence patterns.</p>
                </div>
              ) : relatedItems && relatedItems.length > 0 ? (
                <div className="space-y-6 flex flex-col items-stretch">
                  {relatedItems.map((item: any, idx: number) => (
                    <motion.div
                      key={item.id}
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: idx * 0.1 }}
                    >
                      <FeedCard item={item} viewMode="compact" index={idx} />
                    </motion.div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-32 text-center opacity-30">
                  <Orbit className="w-12 h-12 text-text-ghost mb-4" />
                  <p className="text-xs font-display font-bold text-text-muted uppercase tracking-widest">Isolated Signal</p>
                  <p className="text-[10px] text-text-muted mt-2 px-8">No cross-resonant patterns detected for this entity.</p>
                </div>
              )}
            </div>
            
            {/* Footer / Status */}
            <div className="px-8 py-4 border-t border-white/5 bg-black/20 text-center">
              <span className="text-[9px] font-mono font-bold text-text-ghost uppercase tracking-[0.3em]">Synchronization Active</span>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}


