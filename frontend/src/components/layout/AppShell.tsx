import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { X } from 'lucide-react'
import { usePaletteStore } from '../../store/panelStore'
import { Button } from '../../ui/Button'
import { CommandPalette } from '../command/CommandPalette'
import { PaperPanel } from '../paper/PaperPanel'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

/** Sidebar, top bar and page, plus the two overlays every page shares: ⌘K search and the paper panel. */
export function AppShell() {
  const [navOpen, setNavOpen] = useState(false)
  const openPalette = usePaletteStore((s) => s.open)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        openPalette()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openPalette])

  return (
    <div className="flex min-h-screen bg-bg text-fg">
      <Sidebar className="max-md:hidden" />

      {navOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-bg/70" onClick={() => setNavOpen(false)} aria-hidden="true" />
          <div className="absolute inset-y-0 left-0 flex w-[260px] flex-col border-r border-line bg-surface">
            <Button variant="ghost" size="icon" className="absolute top-3 right-3" onClick={() => setNavOpen(false)} aria-label="Close navigation">
              <X />
            </Button>
            <Sidebar compact={false} onNavigate={() => setNavOpen(false)} className="h-full" />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setNavOpen(true)} />
        <main className="flex-1 px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>

      <PaperPanel />
      <CommandPalette />
    </div>
  )
}
