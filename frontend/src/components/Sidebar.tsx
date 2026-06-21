import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { LayoutGrid, Layers, Bookmark, Settings, RefreshCw, BookOpen } from 'lucide-react'
import { SearchInput } from './SearchInput'
import { apiClient } from '../api/client'
import { SyncLogsModal } from './SyncLogsModal'
import { ThemeToggle } from './shared/ThemeToggle'

interface SidebarProps {
  onClose: () => void
  isCondensed: boolean
  isOpen?: boolean
  onSearchClick?: () => void
}

export function Sidebar({ onClose, isCondensed, onSearchClick }: SidebarProps) {
  const [isSyncing, setIsSyncing] = useState(false)
  const [isLogsOpen, setIsLogsOpen] = useState(false)

  const handleSync = async () => {
    if (isSyncing) {
      setIsLogsOpen(true) // Just open the logs if already syncing
      return
    }
    
    setIsLogsOpen(true)
    setIsSyncing(true)
    try {
      await apiClient.post('/sync')
    } catch (error) {
      console.error('Sync failed:', error)
    } finally {
      // Keep syncing state for visual feedback until logs show progress
      // or the user manually closes it.
      // We don't auto-close the modal or stop syncing state immediately
      // because the actual scraping happens in the background.
      setTimeout(() => setIsSyncing(false), 5000)
    }
  }

  const navItems = [
    { to: '/', icon: LayoutGrid, label: 'Feed', section: 'DISCOVER' },
    { to: '/saved', icon: Bookmark, label: 'Saved', section: 'DISCOVER' },
    { to: '/research', icon: BookOpen, label: 'Research', section: 'DISCOVER' },
    { to: '/clusters', icon: Layers, label: 'Topics', section: 'MANAGE' },
  ]

  const navLinks = (
    <div className="space-y-6">
      <div>
        {!isCondensed && (
          <p className="px-4 mb-2 text-[10px] font-display font-medium tracking-[0.15em] text-text-ghost">
            DISCOVER
          </p>
        )}
        <div className="space-y-1 px-2">
          {navItems.filter(i => i.section === 'DISCOVER').map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md transition-all duration-300 group ${
                  isActive 
                    ? 'text-text-primary' 
                    : 'text-text-muted hover:text-text-secondary hover:bg-white/5'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <div className="relative">
                    <item.icon className={`w-[18px] h-[18px] transition-all duration-300 ${
                      isActive ? 'text-accent-primary drop-shadow-[0_0_8px_rgba(76,95,255,0.5)]' : ''
                    }`} />
                  </div>
                  {!isCondensed && <span className="text-[13px] font-display font-medium tracking-wide">{item.label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </div>

      <div>
        {!isCondensed && (
          <p className="px-4 mb-2 text-[10px] font-display font-medium tracking-[0.15em] text-text-ghost">
            MANAGE
          </p>
        )}
        <div className="space-y-1 px-2">
          {navItems.filter(i => i.section === 'MANAGE').map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md transition-all duration-300 group ${
                  isActive 
                    ? 'text-text-primary' 
                    : 'text-text-muted hover:text-text-secondary hover:bg-white/5'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon className={`w-[18px] h-[18px] transition-all duration-300 ${
                    isActive ? 'text-accent-primary drop-shadow-[0_0_8px_rgba(76,95,255,0.5)]' : ''
                  }`} />
                  {!isCondensed && <span className="text-[13px] font-display font-medium tracking-wide">{item.label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  )

  return (
    <aside className={`
      h-screen sticky top-0 z-40 transition-all duration-500 ease-glass
      ${isCondensed ? 'w-20' : 'w-64'}
      hidden md:flex flex-col border-r border-border-subtle bg-glass-fill backdrop-blur-glass
    `}>
      <div className="p-6 mb-2">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-accent-primary/20 border border-accent-primary/30 flex items-center justify-center shadow-[0_0_15px_rgba(76,95,255,0.2)]">
            <div className="w-4 h-4 bg-accent-primary rounded-sm animate-pulse" />
          </div>
          {!isCondensed && <h1 className="text-xl font-display font-bold tracking-tight text-text-primary">Athena</h1>}
        </div>
      </div>

      <div className="px-4 mb-8">
        <SearchInput isCondensed={isCondensed} onFocus={onSearchClick} />
      </div>

      <nav className="flex-1 overflow-y-auto custom-scrollbar">
        {navLinks}
      </nav>

      <div className="p-4 mt-auto border-t border-border-subtle space-y-2">
        <button
          onClick={handleSync}
          disabled={isSyncing}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md transition-all duration-300 ${
            isSyncing 
              ? 'text-accent-primary bg-accent-primary/10 cursor-not-allowed' 
              : 'text-text-muted hover:text-text-primary hover:bg-white/5'
          }`}
          title="Sync all sources"
        >
          <RefreshCw className={`w-[18px] h-[18px] ${isSyncing ? 'animate-spin' : ''}`} />
          {!isCondensed && <span className="text-[13px] font-display font-medium">Sync Data</span>}
        </button>

        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-md transition-all duration-300 ${
              isActive ? 'text-text-primary bg-white/5' : 'text-text-muted hover:text-text-primary'
            }`
          }
        >
          <Settings className="w-[18px] h-[18px]" />
          {!isCondensed && <span className="text-[13px] font-display font-medium">Settings</span>}
        </NavLink>

        <div className="pt-2">
          <ThemeToggle 
            className="w-full justify-start md:px-3 bg-white/0 hover:bg-white/5 active:bg-white/10" 
            showLabel={!isCondensed} 
          />
        </div>
      </div>
      <SyncLogsModal 
        isOpen={isLogsOpen} 
        onClose={() => setIsLogsOpen(false)} 
      />
    </aside>
  )
}
