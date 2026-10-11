import { useEffect } from 'react'
import { ExternalLink, Maximize2, X } from 'lucide-react'
import { motion } from 'framer-motion'
import { useItemDetail } from '../../api/queries'
import { usePanelStore } from '../../store/panelStore'
import { Button, ButtonLink } from '../../ui/Button'
import { buttonClass } from '../../ui/buttonClass'
import { SaveMenu } from '../items/SaveMenu'
import { PaperDetail } from './PaperDetail'

/** The side panel that opens beside any list when an item is clicked. It keeps your place in the list. */
export function PaperPanel() {
  const itemId = usePanelStore((s) => s.itemId)
  const item = usePanelStore((s) => s.item)
  const close = usePanelStore((s) => s.close)
  // Opened from a related item or search, the panel may only know the id; the details fill in the link.
  const { data } = useItemDetail(itemId ?? '', !!itemId)
  const url = item?.url ?? data?.url

  useEffect(() => {
    if (!itemId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [itemId, close])

  if (!itemId) return null

  return (
    <>
      <div className="fixed inset-0 z-40 bg-bg/50 xl:hidden" onClick={close} aria-hidden="true" />
      <motion.aside
        key={itemId}
        initial={{ x: 24, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col border-l border-line bg-surface shadow-pop"
        aria-label="Item details"
      >
        <header className="flex h-12 shrink-0 items-center gap-0.5 border-b border-line px-3">
          <span className="flex-1 px-1 text-[12px] text-fg-3">Details</span>
          <SaveMenu itemId={itemId} size="icon" />
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer" title="Open the original" aria-label="Open the original" className={buttonClass('ghost', 'icon')}>
              <ExternalLink />
            </a>
          )}
          <ButtonLink to={`/items/${itemId}`} onClick={close} variant="ghost" size="icon" title="Open as a full page" aria-label="Open as a full page">
            <Maximize2 />
          </ButtonLink>
          <Button variant="ghost" size="icon" onClick={close} title="Close (Esc)" aria-label="Close">
            <X />
          </Button>
        </header>
        <div className="flex-1 overflow-y-auto">
          <PaperDetail key={itemId} itemId={itemId} initial={item} layout="panel" />
        </div>
      </motion.aside>
    </>
  )
}
