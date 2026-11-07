import { useEffect, useRef, useState } from 'react'
import type { ConfKind } from '../../api/queries/conferences'

/** 0.1234 → "12.3%" */
export const pct = (share: number, digits = 1) => `${(share * 100).toFixed(digits)}%`

export const KIND_LABEL: Record<ConfKind, string> = { main: 'Main', findings: 'Findings', journal: 'Journal' }

/** The categorical slots in their fixed order (dark steps, validated against the surface): colour follows a topic,
 * never its rank, so a topic keeps its colour while others are added or removed. */
export const SERIES_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300']
export const MAX_SERIES = SERIES_COLORS.length

/** The width of an element, kept up to date, for charts that draw in pixels. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}
