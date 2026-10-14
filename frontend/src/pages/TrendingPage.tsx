import { useState } from 'react'
import { Flame, Sparkles, TrendingUp } from 'lucide-react'
import { useTrending } from '../api/queries'
import { useRising, type RisingWindow } from '../api/queries/momentum'
import { RisingList } from '../features/momentum/RisingList'
import { ItemList } from '../components/items/ItemRow'
import { timeAgo } from '../components/items/format'
import { useAppStore } from '../store/appStore'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { Segmented } from '../ui/Segmented'
import { SkeletonRows } from '../ui/Skeleton'

const CATEGORIES = [
  { value: 'all', label: 'All' },
  { value: 'paper', label: 'Papers' },
  { value: 'company_blog', label: 'Lab blogs' },
  { value: 'community_blog', label: 'Community' },
]

/** Papers gathering citations fastest, and what is gaining attention, with an AI-written brief on the theme behind it. */
export function TrendingPage() {
  const category = useAppStore((s) => s.currentCategory)
  const setCategory = useAppStore((s) => s.setCategory)
  const { data, status, error } = useTrending(category)
  const [period, setPeriod] = useState<RisingWindow>('7d')
  const rising = useRising(period, 20)

  return (
    <div className="mx-auto max-w-[920px]">
      <PageHeader title="Trending" description="Feed papers gathering citations fastest, and items gaining attention from citations and discussion." />

      <section className="mb-8 grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold text-fg"><TrendingUp className="h-4 w-4 text-accent" aria-hidden="true" /> Rising fast</h2>
          <Segmented label="Citations gained over" value={period} onChange={setPeriod} className="ml-auto"
            options={[{ value: '7d', label: 'This week' }, { value: '30d', label: 'This month' }]} />
        </div>
        {rising.isLoading ? <SkeletonRows count={3} /> : rising.data?.length ? (
          <RisingList items={rising.data} period={period} />
        ) : (
          <p className="text-[13px] text-fg-3">No feed paper gained citations {period === '7d' ? 'this week' : 'this month'}. Counts come from Semantic Scholar once a day.</p>
        )}
      </section>

      <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-fg"><Flame className="h-4 w-4 text-accent" aria-hidden="true" /> Trending</h2>
      <div className="mb-4">
        <Segmented label="Type" value={category ?? 'all'} options={CATEGORIES} onChange={(v) => setCategory(v === 'all' ? null : v)} />
      </div>

      {data?.brief && (
        <section className="relative mb-4 rounded-xl border border-line bg-surface p-4">
          <span className="ai-ring" aria-hidden="true" />
          <p className="mb-1 flex items-center gap-1.5 text-[12px] text-fg-3">
            <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" /> Brief written by AI {data.brief.generated_at && `· ${timeAgo(data.brief.generated_at)}`}
          </p>
          <h2 className="text-[16px] font-semibold text-fg">{data.brief.theme}</h2>
          <p className="mt-1.5 max-w-[70ch] text-[14px] leading-relaxed text-fg-2">{data.brief.brief}</p>
        </section>
      )}

      {status === 'pending' ? (
        <SkeletonRows count={5} />
      ) : status === 'error' ? (
        <Notice tone="error" title="Trending items could not be loaded">{error?.message}</Notice>
      ) : data.items.length === 0 ? (
        <EmptyState icon={Flame} title="Nothing is trending right now">Trending needs a few days of citation and discussion data. Check back after the next syncs.</EmptyState>
      ) : (
        <ItemList items={data.items} />
      )}
    </div>
  )
}
