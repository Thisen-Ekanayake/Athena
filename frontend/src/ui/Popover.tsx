import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'

/**
 * A menu or panel under (or above) its button, in a portal so overflow never clips it. Closes on an outside click
 * or Escape. ``trigger`` gets the ref to put on its button, whether it is open, and a toggle.
 */
export function Popover({ trigger, children, width = 260, estHeight = 300, align = 'end', label }: {
  trigger: (p: { ref: RefObject<HTMLButtonElement | null>; open: boolean; toggle: () => void }) => ReactNode
  children: ReactNode | ((close: () => void) => ReactNode)
  width?: number
  /** Used only to flip the panel above the button near the bottom of the screen */
  estHeight?: number
  align?: 'start' | 'end'
  label: string
}) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const close = useCallback(() => setOpen(false), [])

  const reposition = useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const wanted = align === 'end' ? r.right - width : r.left
    const left = Math.max(8, Math.min(wanted, window.innerWidth - width - 8))
    const flipUp = r.bottom + 8 + estHeight > window.innerHeight && r.top > estHeight
    setCoords({ top: flipUp ? Math.max(8, r.top - 6 - estHeight) : r.bottom + 6, left })
  }, [align, width, estHeight])

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

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (triggerRef.current?.contains(t) || panelRef.current?.contains(t)) return
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

  return (
    <>
      {trigger({ ref: triggerRef, open, toggle: () => setOpen((o) => !o) })}
      {open && coords && createPortal(
        <div
          ref={panelRef}
          role="dialog"
          aria-label={label}
          className="fixed z-[70] overflow-hidden rounded-xl border border-line bg-surface shadow-pop"
          style={{ top: coords.top, left: coords.left, width }}
        >
          {typeof children === 'function' ? children(close) : children}
        </div>,
        document.body,
      )}
    </>
  )
}
