import { useFeed } from '../api/queries'
import { useAppStore } from '../store/appStore'
import { FeedTopBar } from '../components/FeedTopBar'
import { FeedCard } from '../components/FeedCard'
import { CardSkeleton } from '../components/CardSkeleton'
import { Alert } from '../components/shared/Alert'
import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Layers, ArrowLeft, Orbit } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import React from 'react'

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
    <div className="flex-1 flex flex-col min-h-screen">
      <FeedTopBar 
        sort={sort} setSort={setSort}
        category={currentCategory} setCategory={setCategory}
        dateRange={dateRange} setDateRange={setDateRange}
        viewMode={viewMode} setViewMode={setViewMode}
      />
      
      <div className="flex-1 w-full max-w-[1200px] mx-auto px-6 py-8 md:px-12 md:py-12">
        <AnimatePresence mode="wait">
          {sourceId && data?.pages[0]?.items[0] && (
            <motion.div 
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="glass-float rounded-2xl px-6 py-5 flex flex-col mb-10 border border-accent-secondary/20"
            >
               <Link to="/" className="text-accent-secondary hover:text-white text-[11px] font-bold tracking-widest flex items-center mb-3 w-fit uppercase transition-all">
                 <ArrowLeft className="w-3.5 h-3.5 mr-1.5" /> Back to Main Feed
               </Link>
               <div className="flex items-center gap-3">
                 <div className="w-10 h-10 rounded-xl bg-accent-secondary/10 flex items-center justify-center text-accent-secondary border border-accent-secondary/20 shadow-glow-secondary">
                   <Layers className="w-5 h-5" />
                 </div>
                 <div>
                   <h2 className="text-xl font-display font-bold text-white tracking-tight">
                     {data?.pages[0]?.items[0]?.source?.name}
                   </h2>
                   <p className="text-[11px] text-text-muted font-medium uppercase tracking-[0.2em]">Source Intelligence Stream</p>
                 </div>
               </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="space-y-6">
          {status === 'pending' ? (
            <div className="grid gap-6">
              {[1, 2, 3].map(i => <CardSkeleton key={i} />)}
            </div>
          ) : status === 'error' ? (
            <Alert type="error" title="Ingestion Failure">
              {(error as Error).message}
            </Alert>
          ) : (
            <div className="grid gap-6">
              {data?.pages.map((group, i) => (
                <React.Fragment key={i}>
                  {group.items.map((item, idx) => (
                    <FeedCard 
                      key={item.id} 
                      item={item} 
                      viewMode={viewMode} 
                      index={idx}
                    />
                  ))}
                </React.Fragment>
              ))}
              
              {isFetchingNextPage && (
                 <div className="flex justify-center p-12">
                   <div className="relative">
                     <div className="w-10 h-10 rounded-full border-2 border-accent-primary/20 animate-ping absolute inset-0" />
                     <div className="w-10 h-10 rounded-full border-2 border-accent-primary border-t-transparent animate-spin relative" />
                   </div>
                 </div>
              )}
              
              {!hasNextPage && data?.pages[0]?.items.length > 0 && (
                 <div className="text-center py-20 opacity-50">
                   <div className="flex items-center justify-center gap-3 text-[11px] font-display font-bold tracking-[0.3em] text-text-ghost uppercase">
                     <div className="h-px w-20 bg-gradient-to-r from-transparent to-border-glow" />
                     SYNCHRONIZATION COMPLETE
                     <div className="h-px w-20 bg-gradient-to-l from-transparent to-border-glow" />
                   </div>
                 </div>
              )}

              {data?.pages[0]?.items.length === 0 && (
                 <div className="flex flex-col items-center justify-center py-32 text-center opacity-40">
                   <div className="w-20 h-20 rounded-full glass-void border border-white/5 flex items-center justify-center mb-6 shadow-inner">
                     <Orbit className="w-10 h-10 text-text-ghost animate-pulse" />
                   </div>
                   <h3 className="text-xl font-display font-medium text-white mb-2">The void is silent</h3>
                   <p className="max-w-xs text-sm text-text-muted">No intelligence matches your current resonance parameters.</p>
                 </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
