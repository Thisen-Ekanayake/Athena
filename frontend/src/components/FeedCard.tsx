import type { FeedItem } from '../api/client'
import { formatDistanceToNow } from 'date-fns'
import { Flame, Layers, Search, ChevronDown, ChevronUp, MessageSquare, ExternalLink, Sparkles } from 'lucide-react'
import { AddToListMenu } from './AddToListMenu'
import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ScoreTooltip } from './ScoreTooltip'
import { ScoreRing } from './ScoreRing'
import { useAppStore } from '../store/appStore'
import { useQAStore } from '../store/qaStore'
import { QAPanel } from './QAPanel'
import { motion, AnimatePresence } from 'framer-motion'

interface FeedCardProps {
  item: FeedItem
  viewMode?: 'compact' | 'expanded'
  index?: number
}

export function FeedCard({ item, viewMode = 'expanded', index = 0 }: FeedCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [showScore, setShowScore] = useState(false)
  const scoreRef = useRef<HTMLDivElement>(null)
  const setRelatedItemId = useAppStore(s => s.setRelatedItemId)

  useEffect(() => {
    if (!showScore) return
    const handleClickOutside = (e: MouseEvent) => {
      if (scoreRef.current && !scoreRef.current.contains(e.target as Node)) {
        setShowScore(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showScore])
  const activeQAItem = useQAStore(s => s.activeItemId)
  const setActiveQAItem = useQAStore(s => s.setActiveItem)
  
  const handleQAPrefetch = () => {
    fetch(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/v1/items/${item.id}/qa/prefetch`).catch(() => {})
  }

  const isCompact = viewMode === 'compact'

  const cardVariants = {
    hidden: { opacity: 0, y: 20, scale: 0.98 },
    visible: (i: number) => ({
      opacity: 1, 
      y: 0,
      scale: 1,
      transition: {
        type: "spring",
        stiffness: 260,
        damping: 20,
        delay: i * 0.05,
      } as any
    })
  }

  return (
    <motion.article 
      layout
      custom={index}
      initial="hidden"
      animate="visible"
      variants={cardVariants}
      whileHover={{ y: -4, transition: { type: "spring", stiffness: 400, damping: 25 } }}
      whileTap={{ scale: 0.99 }}
      className={`group relative glass rounded-lg transition-colors duration-500 ${isCompact ? 'p-4' : 'p-6 mb-6'} hover:glass-float will-change-motion`}
    >
      <div className="flex items-start gap-4">
        {/* Score Ring Section */}
        <div
          ref={scoreRef}
          className="relative flex-shrink-0 cursor-pointer"
          onClick={() => setShowScore(v => !v)}
        >
          <ScoreRing score={item.score} size={isCompact ? 36 : 48} />
          
          <AnimatePresence>
            {showScore && (
              <ScoreTooltip itemId={item.id} score={item.score} isTrending={item.is_trending} />
            )}
          </AnimatePresence>
        </div>

        <div className="flex-1 min-w-0">
          {/* Top Meta Info */}
          <div className="flex items-center gap-2 text-[11px] font-display font-medium mb-1.5 overflow-hidden whitespace-nowrap">
            <Link 
              to={`/sources/${item.source.id}`}
              className="text-text-secondary hover:text-accent-secondary transition-colors"
            >
              {item.source.name.toUpperCase()}
            </Link>
            <span className="text-text-ghost">/</span>
            <span className="text-text-muted">
              {formatDistanceToNow(new Date(item.published_at), { addSuffix: true }).toUpperCase()}
            </span>
            
            <div className="ml-auto flex gap-1.5">
              {item.is_trending && (
                 <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent-tertiary/10 text-accent-tertiary border border-accent-tertiary/20">
                   <Flame className="w-2.5 h-2.5" /> 
                   {!isCompact && <span>TRENDING</span>}
                 </span>
              )}
              {item.category === 'paper' && (
                <span className="px-2 py-0.5 rounded-full bg-accent-secondary/10 text-accent-secondary border border-accent-secondary/20 uppercase">
                  Paper
                </span>
              )}
            </div>
          </div>

          {/* Title */}
          <h2 className={`${isCompact ? 'text-sm' : 'text-lg'} font-display font-bold text-text-primary leading-tight group-hover:text-accent-primary transition-colors cursor-pointer mb-2`}>
            <a href={item.url} target="_blank" rel="noopener noreferrer">
              {item.title}
            </a>
          </h2>

          {/* Summary */}
          {!isCompact && item.summary && (
            <p className="text-text-secondary leading-relaxed text-[13px] line-clamp-3 mb-4">
              {item.summary}
            </p>
          )}

          {/* Expanded Takeaways */}
          {!isCompact && item.takeaways && item.takeaways.length > 0 && (
            <div className="mb-4">
              <button 
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-1.5 text-[11px] font-bold text-accent-primary hover:text-white transition-colors uppercase tracking-wider"
              >
                {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                {expanded ? 'Hide Insights' : `${item.takeaways.length} Key Insights`}
              </button>
              
              <AnimatePresence>
                {expanded && (
                  <motion.ul 
                    layout
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ 
                      height: { type: "spring", stiffness: 300, damping: 30 },
                      opacity: { duration: 0.2 }
                    }}
                    className="mt-3 space-y-2 overflow-hidden"
                  >
                    {item.takeaways.map((t, i) => (
                      <li key={i} className="flex items-start gap-2 text-[13px] text-text-secondary bg-white/3 p-2.5 rounded border border-white/5">
                        <Sparkles className="w-3.5 h-3.5 text-accent-tertiary mt-0.5 flex-shrink-0" />
                        <span>{t}</span>
                      </li>
                    ))}
                  </motion.ul>
                )}
              </AnimatePresence>
            </div>
          )}

          {/* Footer Actions */}
          <div className="flex items-center justify-between pt-3 border-t border-border-subtle mt-2">
            <div className="flex gap-4 items-center">
              {item.cluster && !isCompact && (
                <div className="flex items-center gap-1.5 text-[11px] text-text-muted hover:text-text-primary cursor-pointer transition-colors">
                  <Layers className="w-3.5 h-3.5" />
                  <span className="uppercase tracking-tight">{item.cluster.label}</span>
                </div>
              )}
              
              {item.related_count > 0 && (
                <button 
                  onClick={() => setRelatedItemId(item.id)}
                  className="flex items-center gap-1.5 text-[11px] text-text-muted hover:text-text-primary transition-colors"
                >
                  <Search className="w-3.5 h-3.5" />
                  <span className="uppercase">{item.related_count} RELATED</span>
                </button>
              )}
            </div>

            <div className="flex items-center gap-3">
              {!isCompact && (
                <button 
                  onMouseEnter={handleQAPrefetch}
                  onClick={() => setActiveQAItem(activeQAItem === item.id ? null : item.id)}
                  className="flex items-center gap-1.5 h-8 px-3 rounded-md bg-accent-primary/10 text-accent-primary text-[11px] font-bold hover:bg-accent-primary hover:text-white transition-all duration-300"
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  ASK AI ✦
                </button>
              )}
              
              <div className="flex items-center gap-1">
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-1.5 text-text-muted hover:text-text-primary transition-colors rounded-md hover:bg-white/5"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
                <AddToListMenu itemId={item.id} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Conditionally render QAPanel */}
      {activeQAItem === item.id && (
        <QAPanel item={item} onClose={() => setActiveQAItem(null)} />
      )}
    </motion.article>
  )
}

