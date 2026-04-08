import { useClusters } from '../api/queries'
import { useAppStore } from '../store/appStore'
import { Layers, ArrowRight, Grid2X2, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Alert } from '../components/shared/Alert'
import { motion } from 'framer-motion'

export function ClusterBrowserPage() {
  const { currentCategory } = useAppStore()
  const { data: clusters, isLoading, error } = useClusters(currentCategory)

  const cardVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        delay: i * 0.05,
        duration: 0.5,
        ease: [0.16, 1, 0.3, 1] as any
      }
    })
  }

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      <div className="sticky top-0 z-20 glass-base border-b border-white/5 pt-28 pb-10 px-8 backdrop-blur-xl">
        <div className="max-w-[1200px] mx-auto">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-8 h-8 rounded-lg bg-accent-primary/10 border border-accent-primary/20 flex items-center justify-center text-accent-primary shadow-glow-primary">
              <Grid2X2 className="w-4 h-4" />
            </div>
            <h1 className="text-3xl font-display font-bold text-white tracking-tight">Intelligence <span className="text-accent-primary">Clusters</span></h1>
          </div>
          <p className="text-sm text-text-muted font-medium max-w-2xl">
            Explore dynamically harvested logic structures and specialized research silos across the entire global resonance field.
          </p>
        </div>
      </div>

      <div className="flex-1 w-full max-w-[1200px] mx-auto px-6 py-12 md:px-12">
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} className="glass-void rounded-2xl p-6 h-40 animate-pulse border border-white/5"></div>
            ))}
          </div>
        ) : error ? (
          <Alert type="error" title="Cluster Sync Error">Failed to materialize topic structures.</Alert>
        ) : clusters && clusters.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {clusters.map((cluster, idx) => (
              <motion.div
                key={cluster.id}
                custom={idx}
                initial="hidden"
                animate="visible"
                variants={cardVariants}
                whileHover={{ y: -4 }}
                className="group relative"
              >
                <Link to={`/clusters/${cluster.id}`} className="block h-full glass-opaque hover:glass-float rounded-2xl p-6 border border-white/5 hover:border-accent-primary/30 transition-all duration-500 shadow-lg">
                  <div className="flex justify-between items-start mb-4 gap-4">
                    <h3 className="font-display font-bold text-lg text-text-primary group-hover:text-accent-primary transition-colors line-clamp-2 leading-tight">
                      {cluster.label}
                    </h3>
                    <div className="flex flex-col items-end">
                      <span className="font-mono text-[10px] font-bold text-accent-primary bg-accent-primary/10 px-2 py-0.5 rounded border border-accent-primary/20">
                        {cluster.item_count} ITEMS
                      </span>
                    </div>
                  </div>
                  {cluster.summary && (
                    <p className="text-[13px] text-text-secondary line-clamp-3 leading-relaxed mb-6">
                      {cluster.summary}
                    </p>
                  )}
                  <div className="mt-auto flex items-center justify-between text-[10px] font-display font-bold text-text-ghost tracking-[0.1em] group-hover:text-accent-primary transition-colors uppercase">
                    <div className="flex items-center gap-1.5 ">
                      <Sparkles className="w-3 h-3" />
                      Expand Node
                    </div>
                    <ArrowRight className="w-3 h-3 transform group-hover:translate-x-1 transition-transform" />
                  </div>
                </Link>
                {/* Decorative background glow for hover */}
                <div className="absolute inset-0 -z-10 bg-accent-primary/5 blur-2xl rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
              </motion.div>
            ))}
          </div>
        ) : (
           <div className="flex flex-col items-center justify-center py-32 text-center opacity-40">
             <Layers className="w-12 h-12 text-text-ghost mb-4 animate-pulse" />
             <h3 className="text-xl font-display font-medium text-white mb-2">Cluster Field Empty</h3>
             <p className="max-w-xs text-sm text-text-muted">No specialized logic silos detected in the current category subspace.</p>
           </div>
        )}
      </div>
    </div>
  )
}

