import { useState, type ReactNode } from 'react'
import { apiErrorMessage } from '../../api/error'
import { BASE_SIGNALS, useScoringSettings, useUpdateScoring, type BaseSignal, type CategoryWeights } from '../../api/queries/app_settings'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'

const CATEGORY_LABEL: Record<string, string> = { paper: 'Papers', company_blog: 'Lab blogs', community_blog: 'Community' }
const SIGNAL_LABEL: Record<BaseSignal, { label: string; hint: string }> = {
  citation: { label: 'Citations', hint: 'How often it is cited (papers)' },
  engagement: { label: 'Engagement', hint: 'Votes, comments, stars where a source has them' },
  sentiment: { label: 'Community sentiment', hint: 'How discussion of it reads' },
  recency: { label: 'Recency', hint: 'How new it is, and how fast it gathers citations' },
  authority: { label: 'Source authority', hint: 'How much the source is trusted' },
}

type Form = Record<string, CategoryWeights>

function Title({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-4 grid gap-1">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description && <p className="max-w-[68ch] text-[13px] text-fg-2">{description}</p>}
    </div>
  )
}

const sumOf = (w: CategoryWeights) => BASE_SIGNALS.reduce((t, k) => t + (Number(w[k]) || 0), 0)

/** Admin: the weight of each signal in the relevance score, per kind of item, and the share For you gives a user's interests. */
export function ScoringSettings() {
  const { data, isLoading } = useScoringSettings()
  const update = useUpdateScoring()
  const [edits, setEdits] = useState<Form>({})
  if (isLoading || !data) return <Spinner label="Loading the weights…" />

  const form: Form = Object.fromEntries(Object.entries(data.categories).map(([c, w]) => [c, { ...w, ...edits[c] }]))
  const dirty = Object.keys(edits).length > 0
  const invalid = Object.values(form).some((w) => Math.abs(sumOf(w) - 1) > 0.001)
  const set = (category: string, key: keyof CategoryWeights, value: string) =>
    setEdits((e) => ({ ...e, [category]: { ...form[category], [key]: value === '' ? 0 : Number(value) } }))

  return (
    <section className="grid gap-6">
      <Title
        title="Scoring"
        description="Each item's relevance score is a weighted sum of five signals, with weights per kind of item that add up to 1. Saving a change rescores every item in the background."
      />
      {Object.entries(form).map(([category, w]) => {
        const total = sumOf(w)
        const off = Math.abs(total - 1) > 0.001
        const meta = data.categories[category]
        return (
          <Card key={category} className="grid gap-4 p-4">
            <header className="flex flex-wrap items-center gap-2">
              <h3 className="text-[14px] font-medium text-fg">{CATEGORY_LABEL[category] ?? category}</h3>
              {meta.source === 'saved' ? <Chip>Version {meta.version}</Chip> : <Chip>Defaults</Chip>}
              <span className={cn('ml-auto font-mono text-[12px] tabular-nums', off ? 'text-bad' : 'text-fg-3')}>
                {off ? `adds up to ${total.toFixed(2)}, not 1.00` : 'adds up to 1.00'}
              </span>
            </header>
            <div className="grid gap-3 sm:grid-cols-5">
              {BASE_SIGNALS.map((k) => (
                <label key={k} className="grid content-start gap-1" title={SIGNAL_LABEL[k].hint}>
                  <span className="text-[12px] text-fg-3">{SIGNAL_LABEL[k].label}</span>
                  <input type="number" min={0} max={1} step={0.05} value={w[k]} onChange={(e) => set(category, k, e.target.value)}
                    className={cn(inputClass, 'font-mono')} />
                </label>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-[160px_160px_minmax(0,1fr)] sm:items-end">
              <label className="grid gap-1">
                <span className="text-[12px] text-fg-3">Recency half-life (days)</span>
                <input type="number" min={1} max={365} step={1} value={w.half_life_days} onChange={(e) => set(category, 'half_life_days', e.target.value)}
                  className={cn(inputClass, 'font-mono')} />
              </label>
              <label className="grid gap-1">
                <span className="text-[12px] text-fg-3">Your interests (For you)</span>
                <input type="number" min={0} max={0.8} step={0.05} value={w.preference} onChange={(e) => set(category, 'preference', e.target.value)}
                  className={cn(inputClass, 'font-mono')} />
              </label>
              <p className="text-[11.5px] text-fg-3">
                Not part of the score: the share of each person's For-you order that comes from their own likes and saves
                (the rest is relevance). Changing it re-orders For you without rescoring.
              </p>
            </div>
          </Card>
        )
      })}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" disabled={!dirty || invalid || update.isPending}
          onClick={() => update.mutate(form, { onSuccess: () => setEdits({}) })}>
          {update.isPending ? 'Saving…' : 'Save'}
        </Button>
        {dirty && <Button variant="ghost" onClick={() => setEdits({})}>Discard</Button>}
        {!dirty && update.data && (
          <span className="text-[12.5px] text-fg-3">{update.data.rescoring ? 'Saved. Rescoring started in the background.' : 'Saved.'}</span>
        )}
      </div>
      {update.isError && <Notice tone="error" title="Not saved">{apiErrorMessage(update.error, 'Try again')}</Notice>}
    </section>
  )
}
