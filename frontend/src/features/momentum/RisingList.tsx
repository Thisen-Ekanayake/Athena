import { TrendingUp } from 'lucide-react'
import type { RisingItem, RisingWindow } from '../../api/queries/momentum'
import { timeAgo } from '../../components/items/format'
import { usePanelStore } from '../../store/panelStore'
import { Sparkline } from '../../ui/Sparkline'
import { cn } from '../../ui/cn'

const SPAN: Record<RisingWindow, string> = { '7d': 'this week', '30d': 'this month' }

/** Feed papers gaining citations fastest, each with its gain and a small line of its citations. */
export function RisingList({ items, period, bare = false }: { items: RisingItem[]; period: RisingWindow; bare?: boolean }) {
  const open = usePanelStore((s) => s.open)
  return (
    <ul className={cn('divide-y divide-line', !bare && 'overflow-hidden rounded-xl border border-line bg-surface')}>
      {items.map((item) => (
        <li key={item.id}>
          <button type="button" onClick={() => open(item)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-2/60">
            <span className="min-w-0 flex-1">
              <span className="line-clamp-2 text-[13.5px] font-medium leading-snug text-fg">{item.title}</span>
              <span className="mt-0.5 flex items-center gap-1.5 text-[12px] text-fg-3">
                <TrendingUp className="h-3 w-3 text-accent" aria-hidden="true" />
                <span className="font-medium text-fg-2 tabular-nums">+{item.gain}</span> {SPAN[period]}
                <span aria-hidden="true">·</span> {(item.citation_count ?? 0).toLocaleString()} in all
                <span aria-hidden="true">·</span> {timeAgo(item.published_at)}
              </span>
            </span>
            <Sparkline values={item.series} label={`Citations of ${item.title}: ${item.series[0] ?? 0} to ${item.series[item.series.length - 1] ?? 0}`} />
          </button>
        </li>
      ))}
    </ul>
  )
}
