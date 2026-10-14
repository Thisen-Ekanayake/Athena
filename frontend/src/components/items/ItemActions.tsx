import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, CircleCheck, EyeOff, ExternalLink, MoreHorizontal, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { FeedItem, Reaction } from '../../api/client'
import { useReaction, useSetRead } from '../../api/queries/personal'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'

type Size = 'icon' | 'icon-sm'

/** Mark an item read or unread. */
export function ReadToggle({ itemId, read, size = 'icon-sm', withLabel = false }: {
  itemId: string; read: boolean; size?: Size | 'sm'; withLabel?: boolean
}) {
  const setRead = useSetRead('item')
  const label = read ? 'Read · mark unread' : 'Mark read'
  return (
    <Button
      variant={withLabel ? 'secondary' : 'ghost'}
      size={withLabel ? 'sm' : (size as Size)}
      aria-pressed={read}
      title={label}
      aria-label={withLabel ? undefined : label}
      onClick={() => setRead.mutate({ id: itemId, read: !read })}
      className={cn(read && '[&_svg]:text-good', withLabel && read && 'border-good/40')}
    >
      {read ? <CircleCheck /> : <Check />}
      {withLabel && (read ? 'Read' : 'Mark read')}
    </Button>
  )
}

/** 👍 and 👎: more or less like this in your For-you order. Pressing the active one takes it back. */
export function ReactionButtons({ itemId, reaction, size = 'icon-sm' }: { itemId: string; reaction: Reaction | null | undefined; size?: Size }) {
  const react = useReaction()
  const toggle = (r: Reaction) => react.mutate({ id: itemId, reaction: reaction === r ? null : r })
  return (
    <>
      <Button variant="ghost" size={size} aria-pressed={reaction === 'up'} title="More like this" aria-label="More like this"
        onClick={() => toggle('up')} className={cn(reaction === 'up' && 'text-accent [&_svg]:fill-accent-soft')}>
        <ThumbsUp />
      </Button>
      <Button variant="ghost" size={size} aria-pressed={reaction === 'down'} title="Less like this" aria-label="Less like this"
        onClick={() => toggle('down')} className={cn(reaction === 'down' && 'text-fg [&_svg]:fill-surface-3')}>
        <ThumbsDown />
      </Button>
    </>
  )
}

const MENU_WIDTH = 220

/** "⋯": not interested (leaves your feed), and open the original. */
export function MoreMenu({ item }: { item: FeedItem }) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const react = useReaction()

  const toggle = () => {
    const r = triggerRef.current?.getBoundingClientRect()
    if (open || !r) return setOpen(false)
    const flipUp = r.bottom + 120 > window.innerHeight
    setCoords({ top: flipUp ? r.top - 96 : r.bottom + 6, left: Math.max(8, Math.min(r.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8)) })
    setOpen(true)
  }

  // A small menu: it closes on an outside click, Escape, or when the page scrolls under it.
  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!triggerRef.current?.contains(t) && !menuRef.current?.contains(t)) close()
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

  const entry = 'flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] text-fg hover:bg-surface-2 [&_svg]:h-4 [&_svg]:w-4 [&_svg]:text-fg-3'
  return (
    <>
      <Button ref={triggerRef} variant="ghost" size="icon-sm" title="More" aria-label="More" aria-haspopup="menu" aria-expanded={open}
        onClick={toggle} className={cn(open && 'bg-surface-2 text-fg')}>
        <MoreHorizontal />
      </Button>
      {open && coords && createPortal(
        <div ref={menuRef} role="menu" className="fixed z-[70] overflow-hidden rounded-xl border border-line bg-surface py-1 shadow-pop"
          style={{ top: coords.top, left: coords.left, width: MENU_WIDTH }}>
          <button type="button" role="menuitem" className={entry} onClick={() => { react.mutate({ id: item.id, reaction: 'hide' }); setOpen(false) }}>
            <EyeOff /> Not interested
          </button>
          <a role="menuitem" href={item.url} target="_blank" rel="noopener noreferrer" className={entry} onClick={() => setOpen(false)}>
            <ExternalLink /> Open the original
          </a>
        </div>,
        document.body,
      )}
    </>
  )
}

/** What a hidden item's row becomes: it leaves your feed on the next load, and Undo brings it back. */
export function HiddenRow({ itemId, title }: { itemId: string; title: string }) {
  const react = useReaction()
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-[12.5px] text-fg-3">
      <EyeOff className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">Hidden from your feed: <span className="text-fg-2">{title}</span></span>
      <Button variant="ghost" size="sm" onClick={() => react.mutate({ id: itemId, reaction: null })}>Undo</Button>
    </div>
  )
}
