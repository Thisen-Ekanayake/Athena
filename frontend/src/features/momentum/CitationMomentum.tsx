import { useItemMomentum } from '../../api/queries/momentum'
import { timeAgo } from '../../components/items/format'
import { Spinner } from '../../ui/Spinner'
import { CitationTrend } from './CitationTrend'

const gainText = (n: number | null, span: string) => (n == null ? null : `${n > 0 ? '+' : ''}${n} ${span}`)

/** A feed paper's citations: the gains this week and month, the total, and the last 90 days as a line. */
export function CitationMomentum({ itemId, title }: { itemId: string; title: string }) {
  const { data, isLoading } = useItemMomentum(itemId)
  if (isLoading) return <Spinner />
  if (!data) return null
  const parts = [gainText(data.gain_7d, 'this week'), gainText(data.gain_30d, 'this month'), `${data.total.toLocaleString()} in all`].filter(Boolean)
  const rebuilt = data.series.some((p) => p.rebuilt)

  return (
    <div className="grid gap-2">
      <p className="text-[13px] text-fg-2 tabular-nums">{parts.join(' · ')}</p>
      {data.series.length > 1 && data.total > 0 ? (
        <CitationTrend series={data.series} label={`Citations of ${title} per day over the last ${data.series.length} days`} />
      ) : (
        <p className="text-[12.5px] text-fg-3">No citations yet. Counts are checked once a day.</p>
      )}
      <p className="text-[11.5px] text-fg-3">
        Semantic Scholar{data.fetched_at ? `, checked ${timeAgo(data.fetched_at)}` : ''}.
        {rebuilt && ' The lighter part is rebuilt from when the citing papers came out.'}
      </p>
    </div>
  )
}
