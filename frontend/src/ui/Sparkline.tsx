import { cn } from './cn'

/**
 * A small trend for a row: no axes, a 2px stepped line in the accent, a faint wash under it and a dot on the
 * latest value. One series, so the row's text names it; ``label`` says it for screen readers.
 */
export function Sparkline({ values, label, width = 88, height = 24, className }: {
  values: number[]
  label: string
  width?: number
  height?: number
  className?: string
}) {
  if (values.length < 2) return null
  const pad = 4
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const x = (i: number) => pad + (i * (width - 2 * pad)) / (values.length - 1)
  const y = (v: number) => height - pad - (hi === lo ? 0 : ((v - lo) / (hi - lo)) * (height - 2 * pad))
  // Stepped: a count holds until the day it changes.
  const line = values.map((v, i) => (i === 0 ? `M${x(0)},${y(v)}` : `H${x(i)}V${y(v)}`)).join('')
  const last = values.length - 1
  const area = `${line}V${height - pad}H${x(0)}Z`

  return (
    <svg role="img" aria-label={label} width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('shrink-0 overflow-visible', className)}>
      <path d={area} className="fill-accent" opacity={0.1} />
      <path d={line} fill="none" className="stroke-accent" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(last)} cy={y(values[last])} r={3} className="fill-accent stroke-surface" strokeWidth={1.5} />
    </svg>
  )
}
