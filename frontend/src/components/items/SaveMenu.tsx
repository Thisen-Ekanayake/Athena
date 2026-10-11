import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bookmark, BookmarkCheck, Check, Plus } from 'lucide-react'
import { useAddToList, useCreateList, useLists, useRemoveFromList } from '../../api/queries/saved'
import { apiErrorMessage } from '../../api/error'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'

const MENU_WIDTH = 248
const MENU_EST_HEIGHT = 300 // only used to flip the menu above the button near the bottom of the screen

/** "Save to list": tick the lists an item belongs to, or create a new one. */
export function SaveMenu({ itemId, size = 'icon-sm' }: { itemId: string; size?: 'icon' | 'icon-sm' }) {
  const [open, setOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const { data: lists, isLoading } = useLists(itemId, open)
  const addToList = useAddToList()
  const removeFromList = useRemoveFromList()
  const createList = useCreateList()
  const saved = lists?.some((l) => l.contains_item)

  const close = useCallback(() => {
    setOpen(false)
    setNewName('')
    setError(null)
  }, [])

  const reposition = useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const left = Math.max(8, Math.min(r.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8))
    const flipUp = r.bottom + 8 + MENU_EST_HEIGHT > window.innerHeight
    setCoords({ top: flipUp ? Math.max(8, r.top - 8 - MENU_EST_HEIGHT) : r.bottom + 6, left })
  }, [])

  useLayoutEffect(() => {
    if (!open) return
    reposition()
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [open, reposition])

  // The menu lives in a portal, so an outside click has to miss both the button and the menu.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return
      close()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])

  const create = async () => {
    const name = newName.trim()
    if (!name) return
    setError(null)
    try {
      const list = await createList.mutateAsync(name)
      await addToList.mutateAsync({ listId: list.id, itemId })
      setNewName('')
    } catch (e: unknown) {
      setError(apiErrorMessage(e, 'Could not create the list.'))
    }
  }

  return (
    <>
      <Button
        ref={triggerRef}
        variant="ghost"
        size={size}
        onClick={() => (open ? close() : setOpen(true))}
        title="Save to a list"
        aria-label="Save to a list"
        aria-expanded={open}
        className={cn(open && 'bg-surface-2 text-fg')}
      >
        {saved ? <BookmarkCheck className="text-accent" /> : <Bookmark />}
      </Button>
      {open && coords && createPortal(
        <div
          ref={menuRef}
          role="dialog"
          aria-label="Save to a list"
          className="fixed z-[70] overflow-hidden rounded-xl border border-line bg-surface shadow-pop"
          style={{ top: coords.top, left: coords.left, width: MENU_WIDTH }}
        >
          <p className="border-b border-line px-3 py-2 text-[12px] text-fg-3">Save to a list</p>
          <div className="max-h-56 overflow-y-auto py-1">
            {isLoading ? (
              <div className="flex justify-center py-4"><Spinner /></div>
            ) : lists && lists.length > 0 ? (
              lists.map((list) => {
                const contains = !!list.contains_item
                return (
                  <button
                    key={list.id}
                    type="button"
                    onClick={() => (contains ? removeFromList : addToList).mutate({ listId: list.id, itemId })}
                    className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left hover:bg-surface-2"
                  >
                    <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded border', contains ? 'border-accent bg-accent text-on-primary' : 'border-line-strong')}>
                      {contains && <Check className="h-3 w-3" strokeWidth={3} />}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{list.name}</span>
                    <span className="font-mono text-[11px] text-fg-3">{list.item_count}</span>
                  </button>
                )
              })
            ) : (
              <p className="px-3 py-2 text-[12.5px] text-fg-3">No lists yet. Name one below.</p>
            )}
          </div>
          <form
            className="flex gap-1.5 border-t border-line p-2"
            onSubmit={(e) => {
              e.preventDefault()
              create()
            }}
          >
            <input
              id={`new-list-${itemId}`}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New list, e.g. Computer vision"
              aria-label="New list name"
              className="h-7 min-w-0 flex-1 rounded-md border border-line bg-surface-2 px-2 text-[12.5px] text-fg placeholder:text-fg-3 focus:border-accent-line focus:outline-none"
            />
            <Button type="submit" variant="secondary" size="icon-sm" disabled={!newName.trim() || createList.isPending} aria-label="Create list and save">
              {createList.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Plus />}
            </Button>
          </form>
          {error && <p className="px-3 pb-2 text-[12px] text-bad">{error}</p>}
        </div>,
        document.body,
      )}
    </>
  )
}
