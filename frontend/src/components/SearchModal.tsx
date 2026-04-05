import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, X, Orbit, History, Sparkles } from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'

interface SearchModalProps {
  isOpen: boolean
  onClose: () => void
}

export function SearchModal({ isOpen, onClose }: SearchModalProps) {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isOpen) {
      setQuery('')
      // Small timeout for the animation to start
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [isOpen])

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim().length > 1) {
      navigate(`/search?q=${encodeURIComponent(query.trim())}`)
      onClose()
    }
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-void/80 backdrop-blur-sm"
          />

          {/* Modal Container */}
          <div className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh] px-4 pointer-events-none">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -20 }}
              className="w-full max-w-2xl glass-base border border-white/10 rounded-xl shadow-2xl overflow-hidden pointer-events-auto"
            >
              <form onSubmit={handleSearch} className="relative">
                <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
                  <Search className="w-5 h-5 text-text-muted" />
                </div>
                <input
                  ref={inputRef}
                  type="text"
                  placeholder="Materialize intelligence resonance..."
                  className="w-full bg-transparent border-none py-5 pl-12 pr-12 text-lg text-white placeholder-text-ghost focus:outline-none focus:ring-0"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <div className="absolute inset-y-0 right-4 flex items-center gap-2">
                  <div className="hidden sm:flex items-center gap-1 px-1.5 py-1 rounded border border-white/5 bg-white/5 text-[10px] font-mono text-text-ghost">
                    <span className="text-[12px] leading-none">↩</span>
                    <span>ENTER</span>
                  </div>
                  <button 
                    type="button" 
                    onClick={onClose}
                    className="p-1 hover:bg-white/5 rounded-md transition-colors"
                  >
                    <X className="w-4 h-4 text-text-muted" />
                  </button>
                </div>
              </form>

              {/* Suggestions/Recents area */}
              <div className="border-t border-white/5 p-2">
                <div className="px-3 py-2">
                  <h3 className="text-[10px] font-display font-medium tracking-[0.15em] text-text-ghost uppercase mb-2">
                    RESONANCE PRIMERS
                  </h3>
                  <div className="space-y-1">
                    {[
                      { icon: Sparkles, label: 'Latest Breakthroughs in LLM Reasoning', value: 'LLM Reasoning' },
                      { icon: Orbit, label: 'Emergent Intelligence Patterns', value: 'Emergent Intelligence' },
                      { icon: History, label: 'Historical Convergence Events', value: 'Historical Convergence' }
                    ].map((item) => (
                      <button
                        key={item.value}
                        onClick={() => {
                          setQuery(item.value)
                          navigate(`/search?q=${encodeURIComponent(item.value)}`)
                          onClose()
                        }}
                        className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left text-sm text-text-muted hover:text-white hover:bg-white/5 transition-all group"
                      >
                        <item.icon className="w-4 h-4 text-text-ghost group-hover:text-accent-primary" />
                        <span>{item.label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div className="bg-void/40 px-4 py-2 flex items-center justify-between border-t border-white/5">
                <div className="flex gap-4">
                  <span className="text-[10px] text-text-ghost">
                    <kbd className="font-mono px-1 py-0.5 rounded bg-white/5 border border-white/10 mr-1">↑↓</kbd>
                    Navigate
                  </span>
                  <span className="text-[10px] text-text-ghost">
                    <kbd className="font-mono px-1 py-0.5 rounded bg-white/5 border border-white/10 mr-1">esc</kbd>
                    Close
                  </span>
                </div>
                <div className="flex items-center gap-1 text-[10px] text-accent-primary font-medium italic">
                  <Sparkles className="w-3 h-3" />
                  Semantic Engine Active
                </div>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  )
}
