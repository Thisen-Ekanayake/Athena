import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { cn } from './cn'

const SPEED = 40   // px a second
const END_GAP = 12 // px left clear after the last letter, past the fade

/**
 * One line of text, cut with an ellipsis. While `active` (the row is hovered) a line too long for its box slides
 * to its end and back, as chat titles do in Claude and ChatGPT. Still under reduced motion.
 */
export function MarqueeText({ text, active, className }: { text: string; active: boolean; className?: string }) {
  const box = useRef<HTMLSpanElement>(null)
  const [shift, setShift] = useState(0)

  useLayoutEffect(() => {
    const el = box.current
    const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const over = active && el && !reduced ? el.scrollWidth - el.clientWidth : 0
    setShift(over > 0 ? over + END_GAP : 0)
  }, [active, text])

  const sliding = active && shift > 0
  const style = sliding
    ? { '--marquee-shift': `-${shift}px`, '--marquee-duration': `${Math.max(1.5, shift / SPEED) / 0.7}s` } as CSSProperties
    : undefined
  return (
    <span
      ref={box}
      className={cn(
        'block overflow-hidden whitespace-nowrap',
        sliding ? '[mask-image:linear-gradient(to_right,#000_calc(100%-12px),transparent)]' : 'text-ellipsis',
        className,
      )}
    >
      <span className={cn(sliding && 'marquee')} style={style}>{text}</span>
    </span>
  )
}
