import { useState, type ReactNode } from 'react'
import { X } from 'lucide-react'
import type { Reaction } from '../../api/client'
import { apiErrorMessage } from '../../api/error'
import { useInterests, useMyFeedback, useReaction, useResetFeedback, useSetInterests } from '../../api/queries/personal'
import { timeAgo } from '../../components/items/format'
import { usePanelStore } from '../../store/panelStore'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'

const KINDS: { value: Reaction; label: string; empty: string }[] = [
  { value: 'up', label: 'Liked', empty: 'Nothing liked yet. Use 👍 on an item you want more of.' },
  { value: 'down', label: 'Disliked', empty: 'Nothing disliked yet. Use 👎 on an item you want less of.' },
  { value: 'hide', label: 'Hidden', empty: 'Nothing hidden. "Not interested" in an item\'s ⋯ menu takes it out of your feed.' },
]

function Title({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-4 grid gap-1">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description && <p className="max-w-[68ch] text-[13px] text-fg-2">{description}</p>}
    </div>
  )
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** Each person's own: whether the feed learns from them, what it learned from, and a way to start over. */
export function PersonalisationSettings() {
  const { data, isLoading } = useInterests()
  const setInterests = useSetInterests()
  const reset = useResetFeedback()
  const [confirm, setConfirm] = useState(false)
  if (isLoading || !data) return <Spinner label="Loading…" />
  const { counts } = data

  return (
    <section className="grid gap-8">
      <div>
        <Title
          title="Personalisation"
          description={<>The <b>For you</b> order on the Feed blends each item's relevance with how close it is to what you liked and saved. Only you see it; relevance and scores stay the same for everyone.</>}
        />
        <label className="flex items-baseline gap-2.5 text-[13px]">
          <input type="checkbox" checked={data.enabled} disabled={setInterests.isPending}
            onChange={(e) => setInterests.mutate(e.target.checked)} className="translate-y-[2px] accent-[var(--accent)]" />
          <span className="text-fg">Personalise my feed</span>
          <span className="text-[12px] text-fg-3">Off: no For you order. Hidden items stay hidden.</span>
        </label>
        <p className="mt-3 text-[13px] text-fg-2">
          Learning from {plural(counts.up, 'like')}, {plural(counts.saved, 'saved item')}, {plural(counts.down, 'dislike')} and {plural(counts.hide, 'hidden item')}.
          {!data.ready && ` For you follows your interests fully from ${data.full_at} of these; until then it only nudges the order.`}
        </p>
        {setInterests.error && <p className="mt-2 text-[12px] text-bad">{apiErrorMessage(setInterests.error, 'Not saved')}</p>}
      </div>

      <ReactedItems />

      <div>
        <Title title="Start over" description="Forget every 👍, 👎 and hidden item. Saved items stay in your lists and still count as liked." />
        {confirm ? (
          <Notice tone="warn" title="Forget what Athena learned from your reactions?">
            <div className="mt-2 flex gap-2">
              <Button size="sm" variant="primary" onClick={() => reset.mutate(undefined, { onSettled: () => setConfirm(false) })}>
                {reset.isPending ? 'Forgetting…' : 'Forget my reactions'}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setConfirm(false)}>Keep them</Button>
            </div>
          </Notice>
        ) : (
          <Button variant="secondary" disabled={counts.up + counts.down + counts.hide === 0} onClick={() => setConfirm(true)}>Reset what Athena learned</Button>
        )}
        {reset.data && <p className="mt-2 text-[12.5px] text-fg-3">Forgot {plural(reset.data.removed, 'reaction')}.</p>}
      </div>
    </section>
  )
}

function ReactedItems() {
  const [kind, setKind] = useState<Reaction>('up')
  const { data, isLoading } = useMyFeedback(kind)
  const react = useReaction()
  const open = usePanelStore((s) => s.open)
  const meta = KINDS.find((k) => k.value === kind)!

  return (
    <div>
      <Title title="What you reacted to" description="Remove one to take it out of what For you learns from; removing a hidden item brings it back to your feed." />
      <Segmented label="Reaction" value={kind} options={KINDS.map(({ value, label }) => ({ value, label }))} onChange={setKind} className="mb-3" />
      {isLoading ? <Spinner label="Loading…" /> : !data?.length ? (
        <p className="text-[13px] text-fg-3">{meta.empty}</p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
          {data.map((item) => (
            <li key={item.id} className="flex items-center gap-3 px-4 py-2.5">
              <button type="button" onClick={() => open(item.id)} className="min-w-0 flex-1 text-left">
                <span className="block truncate text-[13px] font-medium text-fg hover:underline">{item.title}</span>
                <span className="block text-[12px] text-fg-3">{[item.source, item.reacted_at && timeAgo(item.reacted_at)].filter(Boolean).join(' · ')}</span>
              </button>
              <Button variant="ghost" size="icon-sm" title="Remove" aria-label={`Remove ${item.title}`}
                onClick={() => react.mutate({ id: item.id, reaction: null })}>
                <X />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
