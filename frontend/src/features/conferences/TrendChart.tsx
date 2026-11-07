import { useMemo, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { pct, useWidth } from './format'

export interface TrendSeries {
  id: string
  name: string
  color: string
  /** share per year, aligned with ``years``; null where the venue had no edition */
  values: (number | null)[]
}

const HEIGHT = 260
const PAD = { top: 12, right: 12, bottom: 26, left: 44 }
const LABELS_WIDTH = 150
const LABEL_GAP = 13

function niceStep(max: number): number {
  for (const step of [0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25]) if (max / step <= 5) return step
  return 0.5
}

/**
 * Topic shares over the years as lines (2px, one categorical slot each), from one baseline, with recessive
 * hairline gridlines. A crosshair snaps to the nearest year and its tooltip lists every topic, values first; the
 * arrow keys move it too. A legend is always there; up to four lines are also labelled at their ends when the
 * labels do not collide. "Show table" lists every value.
 */
export function TrendChart({ years, series, label }: { years: number[]; series: TrendSeries[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const [table, setTable] = useState(false)

  const max = Math.max(0.01, ...series.flatMap((s) => s.values.map((v) => v ?? 0)))
  const step = niceStep(max * 1.08)
  const top = Math.ceil((max * 1.08) / step) * step
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)

  const last = (s: TrendSeries) => {
    for (let i = s.values.length - 1; i >= 0; i--) if (s.values[i] !== null) return i
    return -1
  }
  const plotH = HEIGHT - PAD.top - PAD.bottom
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH

  // Direct labels: only for a few lines, and only where they do not collide (then the legend carries them).
  const labels = useMemo(() => {
    if (series.length > 4) return null
    const placed = series.map((s) => ({ s, at: last(s) })).filter((l) => l.at >= 0)
      .map((l) => ({ ...l, y: y(l.s.values[l.at]!) })).sort((a, b) => a.y - b.y)
    for (let i = 1; i < placed.length; i++) if (placed[i].y - placed[i - 1].y < LABEL_GAP) return null
    return placed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, top])
  const right = labels && width > 560 ? LABELS_WIDTH : PAD.right
  const plotW = Math.max(10, width - PAD.left - right)
  const span = Math.max(1, years[years.length - 1] - years[0])
  const x = (i: number) => PAD.left + ((years[i] - years[0]) / span) * plotW

  const yearTicks = useMemo(() => {
    if (years.length <= 1) return years.map((_, i) => i)
    const every = Math.max(1, Math.ceil(years.length / Math.max(2, Math.floor(plotW / 56))))
    const picked = years.map((_, i) => i).filter((i) => i % every === 0)
    if (picked[picked.length - 1] !== years.length - 1) picked.push(years.length - 1)
    return picked
  }, [years, plotW])

  const path = (s: TrendSeries) => {
    let d = ''
    let pen = false
    s.values.forEach((v, i) => {
      if (v === null) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    })
    return d
  }

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - box.left + PAD.left
    let best = 0
    years.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i })
    setHover(best)
  }
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? years.length) - 1))
    else if (e.key === 'ArrowRight') setHover((h) => Math.min(years.length - 1, (h ?? -1) + 1))
    else if (e.key === 'Escape') setHover(null)
    else return
    e.preventDefault()
  }
  const readout = hover === null ? [] : series
    .map((s) => ({ s, v: s.values[hover] }))
    .filter((r) => r.v !== null)
    .sort((a, b) => (b.v ?? 0) - (a.v ?? 0))

  return (
    <figure className="grid gap-3">
      <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Legend">
        {series.map((s) => (
          <li key={s.id} className="flex items-center gap-1.5 text-[12.5px] text-fg-2">
            <span className="h-0.5 w-3.5 rounded-full" style={{ background: s.color }} aria-hidden="true" />
            {s.name}
          </li>
        ))}
      </ul>
      <div ref={ref} className="relative" style={{ height: HEIGHT }} onPointerLeave={() => setHover(null)}>
        {width > 0 && (
          <svg width={width} height={HEIGHT} role="img" aria-label={`${label}. Use the left and right arrow keys to read each year.`}
            tabIndex={0} onKeyDown={onKey} onFocus={() => setHover((h) => h ?? years.length - 1)} onBlur={() => setHover(null)}
            className="block overflow-visible focus-visible:outline-none">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={PAD.left + plotW} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth={1} />
                <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-fg-3 font-mono text-[10.5px]">
                  {pct(t, step < 0.05 ? 1 : 0)}
                </text>
              </g>
            ))}
            {yearTicks.map((i) => (
              <text key={years[i]} x={x(i)} y={HEIGHT - 6} textAnchor="middle" className="fill-fg-3 font-mono text-[10.5px]">{years[i]}</text>
            ))}
            {hover !== null && (
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} stroke="var(--line-strong)" strokeWidth={1} />
            )}
            {series.map((s) => (
              <path key={s.id} d={path(s)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {series.map((s) => {
              const i = hover ?? last(s)
              const v = i >= 0 ? s.values[i] : null
              return v === null || v === undefined ? null : (
                <circle key={s.id} cx={x(i)} cy={y(v)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
              )
            })}
            {labels && right === LABELS_WIDTH && labels.map((l) => (
              <text key={l.s.id} x={x(l.at) + 9} y={l.y} dy="0.32em" className="fill-fg-2 text-[11.5px]">
                {l.s.name.length > 20 ? `${l.s.name.slice(0, 19)}…` : l.s.name}
              </text>
            ))}
            <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="transparent" onPointerMove={onMove} />
          </svg>
        )}
        {hover !== null && readout.length > 0 && (
          <div className="pointer-events-none absolute top-2 z-10 min-w-44 rounded-lg border border-line bg-surface-2 px-2.5 py-2 text-[12px] shadow-[var(--shadow-pop)]"
            style={x(hover) > width / 2 ? { right: width - x(hover) + 10 } : { left: x(hover) + 10 }}>
            <p className="mb-1 font-mono text-fg-3">{years[hover]}</p>
            <ul className="grid gap-0.5">
              {readout.map(({ s, v }) => (
                <li key={s.id} className="flex items-center gap-2">
                  <span className="h-0.5 w-3 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden="true" />
                  <span className="w-11 font-mono font-medium tabular-nums text-fg">{pct(v!)}</span>
                  <span className="truncate text-fg-2">{s.name}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-fg-3">
        <span>Share of each year's papers sorted into topics.</span>
        <button type="button" onClick={() => setTable(!table)} className="text-fg-2 hover:text-fg" aria-expanded={table}>
          {table ? 'Hide table' : 'Show table'}
        </button>
      </figcaption>
      {table && (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-[12px]">
            <caption className="sr-only">{label}</caption>
            <thead>
              <tr className="border-b border-line text-left text-fg-3">
                <th scope="col" className="px-3 py-1.5 font-normal">Year</th>
                {series.map((s) => <th key={s.id} scope="col" className="px-3 py-1.5 text-right font-normal">{s.name}</th>)}
              </tr>
            </thead>
            <tbody>
              {years.map((yr, i) => (
                <tr key={yr} className="border-b border-line last:border-b-0">
                  <th scope="row" className="px-3 py-1 text-left font-mono font-normal text-fg-2">{yr}</th>
                  {series.map((s) => (
                    <td key={s.id} className="px-3 py-1 text-right font-mono tabular-nums text-fg">{s.values[i] === null ? '–' : pct(s.values[i]!)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  )
}
