import { NavLink } from 'react-router-dom'
import { LayoutGrid, Layers, Flame, Settings } from 'lucide-react'
import { SearchInput } from './SearchInput'

interface SidebarProps {
  onClose: () => void
  isCondensed: boolean
  isOpen?: boolean
}

export function Sidebar({ onClose, isCondensed }: SidebarProps) {
  const navItems = [
    { to: '/', icon: LayoutGrid, label: 'Feed', section: 'DISCOVER' },
    { to: '/trending', icon: Flame, label: 'Trending', section: 'DISCOVER' },
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
        <SearchInput isCondensed={isCondensed} />
      </div>

      <nav className="flex-1 overflow-y-auto custom-scrollbar">
        {navLinks}
      </nav>

      <div className="p-4 mt-auto border-t border-border-subtle">
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
      </div>
    </aside>
  )
}
