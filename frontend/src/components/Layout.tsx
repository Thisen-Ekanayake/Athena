import { Outlet, NavLink } from 'react-router-dom'
import { LayoutGrid, Settings, Layers, Menu, Flame } from 'lucide-react'
import { useState } from 'react'
import { SearchInput } from './SearchInput'
import { RelatedSidebar } from './RelatedSidebar'

export function Layout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const navItems = [
    { to: '/', icon: LayoutGrid, label: 'Feed' },
    { to: '/trending', icon: Flame, label: 'Trending' },
    { to: '/clusters', icon: Layers, label: 'Topics' },
  ]

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-background">
      {/* Mobile Header */}
      <header className="md:hidden flex items-center justify-between p-4 border-b border-border bg-card">
        <h1 className="text-xl font-bold tracking-tight text-white">Athena</h1>
        <button onClick={() => setMobileMenuOpen(!mobileMenuOpen)} className="p-2 text-textSecondary">
          <Menu className="w-6 h-6" />
        </button>
      </header>

      {/* Sidebar Navigation */}
      <aside className={`
        ${mobileMenuOpen ? 'flex' : 'hidden'} 
        md:flex w-full md:w-64 border-r border-border bg-card flex-shrink-0 flex-col h-auto md:h-screen md:sticky md:top-0 z-20
      `}>
        <div className="p-6 hidden md:block">
          <h1 className="text-2xl font-bold tracking-tight bg-gradient-to-br from-white to-zinc-400 bg-clip-text text-transparent">Athena</h1>
          <p className="text-xs text-textSecondary mt-1">Research Intelligence</p>
        </div>

        <div className="px-4 py-2">
          <SearchInput />
        </div>

        <nav className="flex-1 px-4 py-4 md:py-2 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                  isActive 
                    ? 'bg-accentPrimary/10 text-accentPrimary' 
                    : 'text-textSecondary hover:bg-zinc-800 hover:text-white'
                }`
              }
              onClick={() => setMobileMenuOpen(false)}
            >
              <item.icon className="w-5 h-5" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-border/50">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                isActive ? 'text-white bg-zinc-800' : 'text-textSecondary hover:text-white hover:bg-zinc-800'
              }`
            }
          >
            <Settings className="w-5 h-5" />
            Settings
          </NavLink>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 flex flex-col h-full md:h-screen relative overflow-y-auto">
        <Outlet />
        <RelatedSidebar />
      </main>
    </div>
  )
}
