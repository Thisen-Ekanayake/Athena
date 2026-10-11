import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Menu, RefreshCw, Search } from 'lucide-react'
import { apiClient } from '../../api/client'
import { useSources } from '../../api/queries/sources'
import { usePaletteStore } from '../../store/panelStore'
import { Button } from '../../ui/Button'
import { Kbd } from '../../ui/Kbd'
import { OwlCoin } from '../../ui/OwlCoin'
import { timeAgo } from '../items/format'
import { SyncDialog } from './SyncLog'

/** The most recent fetch across all sources, as "4 minutes ago". */
function useLastSynced() {
  const { data: sources } = useSources()
  const latest = sources
    ?.map((s) => s.last_fetched_at)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1)
  return latest ? timeAgo(latest) : null
}

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const openPalette = usePaletteStore((s) => s.open)
  const lastSynced = useLastSynced()
  const [showSync, setShowSync] = useState(false)
  const [starting, setStarting] = useState(false)

  const sync = async () => {
    setShowSync(true)
    setStarting(true)
    try {
      await apiClient.post('/sync')
    } catch {
      // The dialog's log shows whether the sync started.
    } finally {
      setStarting(false)
    }
  }

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
      <div className="ml-auto flex items-center gap-3">
        {lastSynced && <span className="text-[12px] whitespace-nowrap text-fg-3 max-lg:hidden">Synced {lastSynced}</span>}
        <Button variant="secondary" size="sm" onClick={sync} disabled={starting} title="Fetch new items from every source">
          <RefreshCw className={starting ? 'animate-spin' : undefined} /> <span className="max-sm:sr-only">Sync</span>
        </Button>
      </div>
      {showSync && <SyncDialog onClose={() => setShowSync(false)} />}
    </div>
  )
}
