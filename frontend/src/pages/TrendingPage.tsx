import { useAppStore } from '../store/appStore'
import { useTrending } from '../api/queries'
import { FeedCard } from '../components/FeedCard'
import { CardSkeleton } from '../components/CardSkeleton'
import { Alert } from '../components/shared/Alert'
import { Flame, Sparkles, TrendingUp, Zap } from 'lucide-react'
import { motion } from 'framer-motion'

export function TrendingPage() {
  const { currentCategory, viewMode } = useAppStore()
  const { data, status, error } = useTrending(currentCategory)

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      {/* Header with Energy Shift */}
      <div className="relative overflow-hidden border-b border-white/5 pt-28 pb-20 px-8">
        {/* Background Atmosphere Overrides for Trending */}
        <div className="absolute inset-0 bg-[#E05A6B]/10 z-0" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[400px] bg-[#E0A94B]/10 blur-[120px] rounded-full z-0" />
        
        <div className="relative z-10 max-w-[1200px] mx-auto text-center flex flex-col items-center">
          <motion.div 
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="w-16 h-16 rounded-3xl glass-float border-accent-tertiary/30 flex items-center justify-center text-accent-tertiary mb-6 shadow-glow-tertiary"
          >
            <TrendingUp className="w-8 h-8" />
          </motion.div>
          <motion.h1 
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.1 }}
            className="text-4xl md:text-5xl font-display font-bold text-white tracking-tight mb-4"
          >
            <span className="text-accent-tertiary">Hot</span> Sync
          </motion.h1>
          <motion.p 
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.2 }}
            className="text-text-secondary text-sm md:text-base max-w-xl font-medium leading-relaxed"
          >
            High-velocity intelligence streams gaining rapid cross-cluster attention in the last 24 cycles.
          </motion.p>
        </div>
      </div>

      <div className="flex-1 w-full max-w-[1200px] mx-auto px-6 py-12 md:px-12">
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="grid gap-8"
        >
          {data?.brief && (
            <div className="glass-float rounded-2xl overflow-hidden border-accent-tertiary/20 group hover:border-accent-tertiary/40 transition-all duration-500">
              <div className="bg-accent-tertiary/10 px-8 py-4 flex items-center justify-between border-b border-accent-tertiary/20">
                <div className="flex items-center gap-3">
                  <Zap className="w-5 h-5 text-accent-tertiary" />
                  <span className="text-xs font-display font-bold tracking-[0.2em] text-accent-tertiary uppercase">Velocity Intelligence: {data.brief.theme}</span>
                </div>
                <Sparkles className="w-4 h-4 text-accent-tertiary/50" />
              </div>
              <div className="p-8">
                <p className="text-text-primary leading-relaxed font-medium">
                  {data.brief.brief}
                </p>
              </div>
            </div>
          )}

          <div className="space-y-6">
            {status === 'pending' ? (
              <div className="grid gap-6">
                {[1, 2, 3].map(i => <CardSkeleton key={i} />)}
              </div>
            ) : status === 'error' ? (
              <Alert type="error" title="Stream Disturbance">
                {(error as Error).message}
              </Alert>
            ) : (
              <div className="grid gap-6">
                {data?.items.length === 0 ? (
                   <div className="flex flex-col items-center justify-center py-24 text-center opacity-40">
                     <Flame className="w-12 h-12 text-text-ghost mb-4" />
                     <h3 className="text-lg font-display font-medium text-white">Quiet Signal</h3>
                     <p className="text-sm text-text-muted">No high-velocity updates in the current category.</p>
                   </div>
                ) : (
                  data?.items.map((item, idx) => (
                    <FeedCard key={item.id} item={item} viewMode={viewMode} index={idx} />
                  ))
                )}
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  )
}

