import { useState } from 'react'
import type { YearCount } from '../evolution/api'
import { cn } from '../../ui/cn'

const HEIGHT = 88

/**
 * Citations per calendar year as columns (at most 24px wide, rounded tops, from one baseline). The current year is
 * still running, so it is drawn lighter and labelled "so far". One series, so no legend. The largest year and the
 * current one carry their value; hover or focus any column for its own, and a hidden table lists them all.
 */
export function YearBars({ years, label }: { years: YearCount[]; label: string }) {
  const [hover, setHover] = useState<number | null>(null)
  if (!years.length || years.every((y) => y.citations === 0)) return null
  const top = Math.max(...years.map((y) => y.citations), 1)
  const peak = years.reduce((best, y, i) => (y.citations > years[best].citations ? i : best), 0)
  const shown = hover === null ? null : years[hover]

  return (
    <figure className="grid gap-1">
      <div className="relative" style={{ height: HEIGHT + 16 }} onPointerLeave={() => setHover(null)}>
        <div className="absolute inset-x-0 bottom-0 h-px bg-line" aria-hidden="true" />
        <div className="absolute inset-0 flex items-end gap-[2px]" role="group" aria-label={label}>
          {years.map((y, i) => {
            const labelled = (i === peak || y.partial) && y.citations > 0
            return (
              <button
                key={y.year}
                type="button"
                aria-label={`${y.year}${y.partial ? ' so far' : ''}: ${y.citations.toLocaleString()} citations`}
                onPointerEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                className="flex h-full min-w-0 flex-1 flex-col items-center justify-end rounded-sm focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-line"
              >
                {labelled && <span className="mb-0.5 font-mono text-[10.5px] tabular-nums text-fg-2">{y.citations.toLocaleString()}</span>}
                <span
                  className={cn('block w-full max-w-[24px] rounded-t-[4px] bg-accent transition-opacity',
                    y.partial && 'opacity-45', hover !== null && hover !== i && 'opacity-60')}
                  style={{ height: y.citations ? `max(2px, ${(y.citations / top) * HEIGHT}px)` : 0 }}
                />
              </button>
            )
          })}
        </div>
        {shown && (
          <div
            className="pointer-events-none absolute bottom-full z-10 mb-1 w-max -translate-x-1/2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-[12px] shadow-[var(--shadow-pop)]"
            style={{ left: `clamp(56px, ${((hover! + 0.5) / years.length) * 100}%, calc(100% - 56px))` }}
          >
            <p className="font-medium text-fg tabular-nums">{shown.citations.toLocaleString()} citations</p>
            <p className="text-fg-3">{shown.year}{shown.partial ? ', so far' : ''}</p>
          </div>
        )}
      </div>
      <div className="flex gap-[2px] text-[10.5px] text-fg-3" aria-hidden="true">
        {years.map((y, i) => (
          <span key={y.year} className="min-w-0 flex-1 text-center tabular-nums">
            {i === 0 || i === years.length - 1 || y.partial ? (y.partial ? `${y.year}*` : y.year) : ''}
          </span>
        ))}
      </div>
      {years.some((y) => y.partial) && <figcaption className="text-[11px] text-fg-3">* so far this year</figcaption>}
      <table className="sr-only">
        <caption>{label}</caption>
        <thead><tr><th>Year</th><th>Citations</th></tr></thead>
        <tbody>{years.map((y) => <tr key={y.year}><td>{y.year}{y.partial ? ' (so far)' : ''}</td><td>{y.citations}</td></tr>)}</tbody>
      </table>
    </figure>
  )
}
