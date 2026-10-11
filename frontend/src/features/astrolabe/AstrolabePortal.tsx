import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../../store/appStore'
import { cn } from '../../ui/cn'
import type { AstrolabeHandle } from './scene'

/** The animated astrolabe on Home. Clicking its centre opens search. */
export function AstrolabePortal({ onCoreClick, className }: { onCoreClick?: () => void; className?: string }) {
  const accent = useAppStore((s) => s.accent)
  const wrapRef = useRef<HTMLDivElement>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const clickRef = useRef(onCoreClick)
  const [hoverCore, setHoverCore] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    clickRef.current = onCoreClick
  }, [onCoreClick])

  // Rebuilt when the accent changes. Each build makes its own canvas, so two builds never share a
  // WebGL context (StrictMode mounts effects twice in development).
  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const canvas = document.createElement('canvas')
    canvas.className = 'absolute inset-0 block h-full w-full'
    canvas.setAttribute('role', 'img')
    canvas.setAttribute('aria-label', 'Animated astrolabe. Click the centre to search.')
    wrap.prepend(canvas)
    let handle: AstrolabeHandle | null = null
    let dead = false
    import('./scene')
      .then(({ createAstrolabe }) =>
        createAstrolabe(canvas, {
          mode: 'portal',
          paletteEl: wrap,
          onCoreHover: setHoverCore,
          onPointer: (x, y, w) => {
            const tip = tipRef.current
            if (!tip) return
            tip.style.left = `${Math.min(Math.max(x, 100), w - 100)}px`
            tip.style.top = `${y}px`
          },
          onCoreClick: () => clickRef.current?.(),
        }),
      )
      .then((h) => {
        if (dead) h.destroy()
        else handle = h
      })
      .catch(() => {
        if (!dead) setFailed(true)
      })
    return () => {
      dead = true
      handle?.destroy()
      canvas.remove()
    }
  }, [accent])

  return (
    <div ref={wrapRef} className={cn('relative min-w-0', className)}>
      {failed && (
        <div
          className="absolute top-1/2 left-1/2 aspect-square w-[min(62%,300px)] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{ background: 'radial-gradient(circle, var(--neb-1), var(--sky) 65%)', boxShadow: '0 0 0 5px var(--metal), 0 0 0 22px transparent, 0 0 0 23px var(--metal)' }}
        />
      )}
      <div
        ref={tipRef}
        hidden={!hoverCore}
        className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+16px)] whitespace-nowrap rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] text-fg-3 shadow-pop"
      >
        <b className="block text-[13px] font-medium text-fg">Ask Athena</b>
        Click to search or ask
      </div>
    </div>
  )
}
