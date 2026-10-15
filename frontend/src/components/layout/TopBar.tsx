import { Link } from 'react-router-dom'
import { Menu, Search } from 'lucide-react'
import { usePaletteStore } from '../../store/panelStore'
import { Button } from '../../ui/Button'
import { Kbd } from '../../ui/Kbd'
import { OwlCoin } from '../../ui/OwlCoin'
import { InboxBell } from './InboxBell'

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const openPalette = usePaletteStore((s) => s.open)

  return (
    <div className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur-md md:px-6">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={onMenu} aria-label="Open navigation">
        <Menu />
      </Button>
      <Link to="/" className="md:hidden" aria-label="Athena home"><OwlCoin size={24} /></Link>
      <button
        type="button"
        onClick={() => openPalette()}
        className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 text-left text-[13px] text-fg-3 transition-colors hover:border-line-strong md:max-w-[420px]"
      >
        <Search className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">Search papers and topics, or ask a question</span>
        <Kbd className="max-sm:hidden">⌘K</Kbd>
      </button>
      {/* Sync lives in the sidebar now; the bell takes its corner */}
      <div className="ml-auto flex items-center">
        <InboxBell />
      </div>
    </div>
  )
}
