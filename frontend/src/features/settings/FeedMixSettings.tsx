import { useState } from 'react'
import { apiErrorMessage } from '../../api/error'
import { useFeedSettings, useUpdateFeedSettings } from '../../api/queries/app_settings'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'

/** Admin: the most of a feed page one source may fill, so a prolific source can't crowd out the rest. */
export function FeedMixSettings() {
  const { data, isLoading } = useFeedSettings()
  const update = useUpdateFeedSettings()
  const [edit, setEdit] = useState<string | null>(null)
  if (isLoading || !data) return <Spinner label="Loading the feed mix…" />

  const percent = edit ?? String(Math.round(data.source_share * 100))
  const value = Number(percent)
  const invalid = percent === '' || !Number.isFinite(value) || value <= 0 || value > 100
  const perPage = Math.max(1, Math.floor((value / 100) * 20))

  return (
    <Card className="grid gap-3 p-4">
      <header className="grid gap-1">
        <h3 className="text-[14px] font-medium text-fg">Feed mix</h3>
        <p className="max-w-[68ch] text-[12.5px] text-fg-2">
          The most of a feed page one source may fill, in the Relevance and For-you orders. Newest and a single source's
          feed are left as they are. 100% turns the cap off.
        </p>
      </header>
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1">
          <span className="text-[12px] text-fg-3">One source at most (%)</span>
          <input type="number" min={1} max={100} step={5} value={percent} onChange={(e) => setEdit(e.target.value)}
            className={cn(inputClass, 'w-[120px] font-mono')} />
        </label>
        <span className={cn('pb-2 text-[12px]', invalid ? 'text-bad' : 'text-fg-3')}>
          {invalid ? 'Between 1 and 100' : value >= 100 ? 'No cap' : `${perPage} of every 20 items`}
        </span>
        <Button variant="primary" className="ml-auto" disabled={edit === null || invalid || update.isPending}
          onClick={() => update.mutate(value / 100, { onSuccess: () => setEdit(null) })}>
          {update.isPending ? 'Saving…' : 'Save'}
        </Button>
      </div>
      {update.isError && <Notice tone="error" title="Not saved">{apiErrorMessage(update.error, 'Try again')}</Notice>}
    </Card>
  )
}
