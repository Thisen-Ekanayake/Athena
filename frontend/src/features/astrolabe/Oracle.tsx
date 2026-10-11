import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../../store/appStore'
import type { AstrolabeHandle, OracleMode } from './scene'

/** The astrolabe in miniature. It wakes while the AI works ('thinking') and settles when it is done. */
export function Oracle({ mode, size = 64 }: { mode: OracleMode; size?: number }) {
  const accent = useAppStore((s) => s.accent)
  const wrapRef = useRef<HTMLDivElement>(null)
  const handleRef = useRef<AstrolabeHandle | null>(null)
  const modeRef = useRef(mode)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    modeRef.current = mode
    handleRef.current?.setMode(mode)
  }, [mode])

  // Each build makes its own canvas, so two builds never share a WebGL context.
  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap) return
    const canvas = document.createElement('canvas')
    canvas.className = 'absolute inset-0 block h-full w-full'
    wrap.prepend(canvas)
    let dead = false
    import('./scene')
      .then(({ createAstrolabe }) => createAstrolabe(canvas, { mode: 'oracle', paletteEl: wrap, initialMode: modeRef.current }))
      .then((h) => {
        if (dead) h.destroy()
        else handleRef.current = h
      })
      .catch(() => {
        if (!dead) setFailed(true)
      })
    return () => {
      dead = true
      handleRef.current?.destroy()
      handleRef.current = null
      canvas.remove()
    }
  }, [accent])

  return (
    <div ref={wrapRef} className="relative shrink-0" style={{ width: size, height: size }} aria-hidden="true">
      {failed && (
        <div
          className="absolute inset-[16%] rounded-full"
          style={{ background: 'radial-gradient(circle, var(--neb-1), var(--sky) 70%)', boxShadow: '0 0 0 3px var(--metal)' }}
        />
      )}
    </div>
  )
}
