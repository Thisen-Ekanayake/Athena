import { Outlet } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import { useState, useEffect } from 'react'
import { Sidebar } from './Sidebar'
import { RelatedSidebar } from './RelatedSidebar'
import { AnimatePresence, motion } from 'framer-motion'

export function Layout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [isCondensed, setIsCondensed] = useState(false)

  useEffect(() => {
    const handleResize = () => {
      const width = window.innerWidth
      setIsCondensed(width >= 768 && width < 1100)
    }

    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return (
    <div className="min-h-screen flex text-text-primary selection:bg-accent-primary/30">
      {/* Mobile Top Header */}
      <header className="md:hidden fixed top-0 left-0 right-0 h-16 flex items-center justify-between px-6 z-50 bg-glass-fill backdrop-blur-glass border-b border-border-subtle">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-accent-primary/20 border border-accent-primary/30 flex items-center justify-center">
            <div className="w-3 h-3 bg-accent-primary rounded-sm" />
          </div>
          <h1 className="text-lg font-display font-bold tracking-tight">Athena</h1>
        </div>
        <button 
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)} 
          className="p-2 -mr-2 text-text-secondary hover:text-text-primary transition-colors"
        >
          {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </header>

      {/* Sidebar - Desktop & Tablet */}
      <Sidebar 
        isOpen={mobileMenuOpen} 
        onClose={() => setMobileMenuOpen(false)} 
        isCondensed={isCondensed} 
      />

      {/* Mobile Sidebar Overlay */}
      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, x: -100 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -100 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-0 z-40 md:hidden bg-glass-fill-active backdrop-blur-glass-heavy border-r border-border-glow"
          >
            <div className="flex flex-col h-full pt-20 px-4">
              <Sidebar 
                isOpen={mobileMenuOpen} 
                onClose={() => setMobileMenuOpen(false)} 
                isCondensed={false} 
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 flex flex-col md:flex-row relative">
        <div className="flex-1 w-full max-w-[1600px] mx-auto flex flex-col md:flex-row">
          <div className="flex-1 pt-20 md:pt-0 overflow-y-auto overflow-x-hidden custom-scrollbar">
            <div className="px-6 py-8 md:px-12 md:py-12">
              <Outlet />
            </div>
          </div>
          
          {/* Related Sidebar - only visible on wide screens (> 1400px) */}
          <div className="hidden min-[1400px]:block">
            <RelatedSidebar />
          </div>
        </div>
      </main>
    </div>
  )
}

