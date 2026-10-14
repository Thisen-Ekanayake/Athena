import { useState, type PointerEvent } from 'react'
import type { MomentumPoint } from '../../api/queries/momentum'
import { cn } from '../../ui/cn'

const HEIGHT = 96
const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', timeZone: 'UTC' })

/** A clean axis top at or above ``value``: 1, 2 or 5 times a power of ten (small counts stay whole numbers). */
function niceTop(value: number) {
  if (value <= 5) return Math.max(1, Math.ceil(value))
  const power = 10 ** Math.floor(Math.log10(value))
  return [1, 2, 5, 10].map((m) => m * power).find((m) => m >= value) ?? 10 * power
}

/**
 * A paper's citations per day: a stepped 2px line from zero, with a faint wash under it. Days rebuilt from the
 * citing papers' dates are drawn lighter than days read on the day. One series, so no legend; hover or focus a
 * day for its count, and a hidden table lists every change.
 */
export function CitationTrend({ series, label }: { series: MomentumPoint[]; label: string }) {
  const [hover, setHover] = useState<number | null>(null)
  if (series.length < 2) return null
  const top = niceTop(Math.max(...series.map((p) => p.citations)))
  const n = series.length
  const x = (i: number) => (i / (n - 1)) * 100
  const y = (v: number) => HEIGHT - (v / top) * HEIGHT
  const path = (from: number, to: number) =>
    series.slice(from, to + 1).map((p, k) => (k === 0 ? `M${x(from)},${y(p.citations)}` : `H${x(from + k)}V${y(p.citations)}`)).join('')
  const firstDaily = series.findIndex((p) => !p.rebuilt)
  const rebuiltEnd = firstDaily === -1 ? n - 1 : firstDaily
  const area = `${path(0, n - 1)}V${HEIGHT}H0Z`
  const changes = series.filter((p, i) => i === 0 || p.citations !== series[i - 1].citations)
  const shown = hover === null ? null : series[hover]

  const pick = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    setHover(Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1)))))
  }

  return (
    <figure className="grid gap-1.5">
      <div className="grid grid-cols-[28px_minmax(0,1fr)] gap-2">
        <div className="relative font-mono text-[10.5px] tabular-nums text-fg-3" style={{ height: HEIGHT }} aria-hidden="true">
          <span className="absolute right-0 top-0 -translate-y-1/2">{top}</span>
          <span className="absolute right-0 bottom-0 translate-y-1/2">0</span>
        </div>
        <div
          className="relative cursor-crosshair outline-none focus-visible:ring-1 focus-visible:ring-accent-line"
          style={{ height: HEIGHT }}
          tabIndex={0}
          role="img"
          aria-label={label}
          onPointerMove={pick}
          onPointerLeave={() => setHover(null)}
          onFocus={() => setHover(n - 1)}
          onBlur={() => setHover(null)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? n - 1) - 1))
            if (e.key === 'ArrowRight') setHover((h) => Math.min(n - 1, (h ?? 0) + 1))
          }}
        >
          <div className="absolute inset-x-0 top-0 h-px bg-line/60" aria-hidden="true" />
          <div className="absolute inset-x-0 bottom-0 h-px bg-line" aria-hidden="true" />
          <svg viewBox={`0 0 100 ${HEIGHT}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
            <path d={area} className="fill-accent" opacity={0.1} />
            {rebuiltEnd > 0 && (
              <path d={path(0, rebuiltEnd)} fill="none" className="stroke-accent" strokeOpacity={0.45} strokeWidth={2}
                vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            )}
            {firstDaily !== -1 && (
              <path d={path(firstDaily, n - 1)} fill="none" className="stroke-accent" strokeWidth={2}
                vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            )}
          </svg>
          {shown && (
            <>
              <div className="pointer-events-none absolute inset-y-0 w-px bg-line-strong" style={{ left: `${x(hover!)}%` }} aria-hidden="true" />
              <span
                className={cn('pointer-events-none absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent ring-2 ring-surface', shown.rebuilt && 'opacity-70')}
                style={{ left: `${x(hover!)}%`, top: `${(y(shown.citations) / HEIGHT) * 100}%` }}
                aria-hidden="true"
              />
              <div
                className="pointer-events-none absolute bottom-full z-10 mb-1.5 w-max -translate-x-1/2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-[12px] shadow-[var(--shadow-pop)]"
                style={{ left: `clamp(70px, ${x(hover!)}%, calc(100% - 70px))` }}
                role="status"
              >
                <p className="font-medium text-fg tabular-nums">{shown.citations.toLocaleString()} {shown.citations === 1 ? 'citation' : 'citations'}</p>
                <p className="text-fg-3">{dayLabel(shown.date)}{shown.rebuilt ? ' · rebuilt from citing papers' : ''}</p>
              </div>
            </>
          )}
        </div>
      </div>
      <div className="grid grid-cols-[28px_minmax(0,1fr)] gap-2 text-[10.5px] text-fg-3" aria-hidden="true">
        <span />
        <div className="flex justify-between"><span>{dayLabel(series[0].date)}</span><span>Today</span></div>
      </div>
      <table className="sr-only">
        <caption>{label}</caption>
        <thead><tr><th>Day</th><th>Citations</th><th>How it is known</th></tr></thead>
        <tbody>
          {changes.map((p) => (
            <tr key={p.date}><td>{dayLabel(p.date)}</td><td>{p.citations}</td><td>{p.rebuilt ? 'rebuilt from citing papers' : 'read that day'}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
