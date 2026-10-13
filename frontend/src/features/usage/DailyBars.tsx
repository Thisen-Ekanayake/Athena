import { useState } from 'react'
import { cn } from '../../ui/cn'
import { compact, usd } from './format'

interface Day {
  day: string
  tokens: number
  cost_usd: number
}

/** A round axis top a little above the largest value: 1, 2 or 5 times a power of ten. */
function niceMax(value: number) {
  const power = 10 ** Math.floor(Math.log10(Math.max(value, 1)))
  return ([1, 2, 5, 10].map((m) => m * power).find((m) => m >= value) ?? 10 * power)
}

const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', timeZone: 'UTC' })

/**
 * Tokens per day across a calendar month (UTC), one bar per day. One series, so no legend: the heading
 * names it. Each day's column is its hover and focus target; a hidden table carries every value.
 */
export function DailyBars({ month, daily, label }: { month: string; daily: Day[]; label: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const [year, mon] = month.split('-').map(Number)
  const length = new Date(Date.UTC(year, mon, 0)).getUTCDate()
  const today = new Date().toISOString().slice(0, 10)
  const byDay = new Map(daily.map((d) => [d.day.slice(0, 10), d]))
  const days = Array.from({ length }, (_, i) => {
    const day = `${month}-${String(i + 1).padStart(2, '0')}`
    return byDay.get(day) ?? { day, tokens: 0, cost_usd: 0 }
  })
  const top = niceMax(Math.max(...days.map((d) => d.tokens), 1))
  const shown = hover === null ? null : days[hover]

  return (
    <figure className="grid gap-2">
      <div className="grid grid-cols-[44px_minmax(0,1fr)] gap-2">
        {/* y axis: zero, half and the top */}
        <div className="relative h-[140px] font-mono text-[10.5px] tabular-nums text-fg-3" aria-hidden="true">
          {[1, 0.5, 0].map((f) => (
            <span key={f} className="absolute right-0 -translate-y-1/2" style={{ top: `${(1 - f) * 100}%` }}>{compact(top * f)}</span>
          ))}
        </div>
        <div className="relative h-[140px]" onPointerLeave={() => setHover(null)}>
          {[1, 0.5].map((f) => (
            <div key={f} className="absolute inset-x-0 h-px bg-line/60" style={{ top: `${(1 - f) * 100}%` }} aria-hidden="true" />
          ))}
          <div className="absolute inset-x-0 bottom-0 h-px bg-line" aria-hidden="true" />
          <div className="absolute inset-0 flex items-end gap-[2px]" role="group" aria-label={label}>
            {days.map((d, i) => (
              <button
                key={d.day}
                type="button"
                aria-label={`${dayLabel(d.day)}: ${d.tokens.toLocaleString()} tokens, ${usd(d.cost_usd)}`}
                onPointerEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                className="flex h-full min-w-0 flex-1 items-end justify-center rounded-sm focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-line"
              >
                <span
                  className={cn('block w-full max-w-[24px] rounded-t-[4px] bg-accent transition-opacity', hover !== null && hover !== i && 'opacity-60')}
                  style={{ height: d.tokens ? `max(2px, ${(d.tokens / top) * 100}%)` : 0 }}
                />
              </button>
            ))}
          </div>
          {shown && (
            <div
              className="pointer-events-none absolute bottom-full z-10 mb-1.5 w-max -translate-x-1/2 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-[12px] shadow-[var(--shadow-pop)]"
              style={{ left: `clamp(60px, ${((hover! + 0.5) / length) * 100}%, calc(100% - 60px))` }}
            >
              <p className="font-medium text-fg tabular-nums">{shown.tokens.toLocaleString()} tokens</p>
              <p className="text-fg-3">{dayLabel(shown.day)} · {usd(shown.cost_usd)}{shown.day === today ? ' · today' : ''}</p>
            </div>
          )}
        </div>
      </div>
      {/* x axis: the first of each week */}
      <div className="grid grid-cols-[44px_minmax(0,1fr)] gap-2 text-[10.5px] text-fg-3" aria-hidden="true">
        <span />
        <div className="relative h-3">
          {[1, 8, 15, 22, 29].filter((n) => n <= length).map((n) => (
            <span key={n} className="absolute -translate-x-1/2" style={{ left: `${((n - 0.5) / length) * 100}%` }}>{dayLabel(days[n - 1].day)}</span>
          ))}
        </div>
      </div>
      <table className="sr-only">
        <caption>{label}</caption>
        <thead><tr><th>Day</th><th>Tokens</th><th>Cost</th></tr></thead>
        <tbody>
          {days.filter((d) => d.tokens).map((d) => (
            <tr key={d.day}><td>{dayLabel(d.day)}</td><td>{d.tokens}</td><td>{usd(d.cost_usd)}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
