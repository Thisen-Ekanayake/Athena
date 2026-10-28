import { useEffect, useRef, useState } from 'react'

/**
 * Shows an element full screen. Without the Fullscreen API (Safari on iPhone) it fills the window
 * instead, and Escape leaves.
 */
export function useFullScreen<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [on, setOn] = useState(false)
  useEffect(() => {
    const sync = () => {
      if (!document.fullscreenElement) setOn(false)
    }
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])
  const leave = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    setOn(false)
  }
  useEffect(() => {
    if (!on) return
    // Browsers usually leave full screen on Escape themselves; this covers the window-filling fallback.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (document.fullscreenElement) void document.exitFullscreen()
      setOn(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [on])
  const toggle = () => {
    if (on) return leave()
    setOn(true)
    if (document.fullscreenEnabled) ref.current?.requestFullscreen().catch(() => {})
  }
  return { ref, on, toggle }
}
