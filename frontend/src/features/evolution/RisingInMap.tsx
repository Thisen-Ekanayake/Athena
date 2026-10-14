import { TrendingUp } from 'lucide-react'
import { Sparkline } from '../../ui/Sparkline'
import { Spinner } from '../../ui/Spinner'
import { useTopicRising } from './api'

/** The map's papers gaining citations fastest: about how many in the last twelve months, and how many times the year before. */
export function RisingInMap({ slug, onSelect }: { slug: string; onSelect: (id: string) => void }) {
  const { data, isLoading } = useTopicRising(slug)
  return (
    <section className="grid gap-2">
      <div className="grid gap-0.5">
        <h3 className="flex items-center gap-2 text-[14px] font-medium text-fg"><TrendingUp className="h-4 w-4 text-accent" aria-hidden="true" /> Rising in this map</h3>
        <p className="text-[12.5px] text-fg-3">Papers gathering citations faster than a year ago, from OpenAlex's yearly counts.</p>
      </div>
      {isLoading ? <Spinner /> : !data?.length ? (
        <p className="text-[13px] text-fg-3">Nothing is rising yet, or the yearly counts have not been fetched; they arrive with the next build or refresh.</p>
      ) : (
        <ol className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
          {data.map((p) => (
            <li key={p.id}>
              <button type="button" onClick={() => onSelect(p.id)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-surface-2/60">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-medium text-fg">{p.named_method ?? p.title}</span>
                  <span className="block text-[12px] text-fg-3 tabular-nums">
                    {p.year ?? 'n.d.'} · about {p.last_12_months.toLocaleString()} citations in the last 12 months
                    {p.previous_12_months > 0 ? `, ${p.ratio.toFixed(1)}× the year before` : ', new this year'}
                  </span>
                </span>
                {/* Full years, then the last twelve months: this year alone is still running and would look like a fall. */}
                <Sparkline values={[...p.citations_by_year.filter((y) => !y.partial).map((y) => y.citations), p.last_12_months]}
                  label={`Citations per year of ${p.title}, ending with the last twelve months`} width={72} />
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
