import { useState } from 'react'
import { TrendingUp } from 'lucide-react'
import { useRising, type RisingWindow } from '../api/queries/momentum'
import { RisingList } from '../features/momentum/RisingList'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { Segmented } from '../ui/Segmented'
import { SkeletonRows } from '../ui/Skeleton'

const SPAN: Record<RisingWindow, string> = { '7d': 'this week', '30d': 'this month' }

/** Feed papers gaining citations fastest: citation momentum is the one "rising" measure. */
export function RisingPage() {
  const [period, setPeriod] = useState<RisingWindow>('7d')
  const rising = useRising(period, 50)

  return (
    <div className="mx-auto max-w-[920px]">
      <PageHeader title="Rising" description="Feed papers gaining the most citations. Counts come from Semantic Scholar once a day." />
      <div className="mb-4">
        <Segmented label="Citations gained over" value={period} onChange={setPeriod}
          options={[{ value: '7d', label: 'This week' }, { value: '30d', label: 'This month' }]} />
      </div>
      {rising.isPending ? (
        <SkeletonRows count={5} />
      ) : rising.isError ? (
        <Notice tone="error" title="Rising papers could not be loaded">{rising.error.message}</Notice>
      ) : rising.data.length ? (
        <RisingList items={rising.data} period={period} />
      ) : (
        <EmptyState icon={TrendingUp} title={`No paper gained citations ${SPAN[period]}`}>
          Citation counts are checked once a day. Papers show up here as soon as one gains a citation.
        </EmptyState>
      )}
    </div>
  )
}
