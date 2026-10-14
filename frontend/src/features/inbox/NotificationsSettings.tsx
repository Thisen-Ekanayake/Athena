import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import {
  useInboxSettings, useSaveInboxSettings, useSetDelivery, useUnfollow, useWatches,
  type Delivery, type InboxSettings, type WatchKind,
} from '../../api/queries/inbox'
import { timeAgo } from '../../components/items/format'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const KIND_LABEL: Record<WatchKind, string> = { map: 'Map', search: 'Search', source: 'Source', cluster: 'Cluster' }
const MUTABLE: { kind: InboxSettings['muted_kinds'][number]; label: string; note: string }[] = [
  { kind: 'map_new', label: 'New maps', note: 'When anyone builds a map' },
  { kind: 'feed_citations', label: 'New papers citing milestones', note: 'For the maps you follow' },
]

/** An hour in UTC as a time of day where the viewer is, e.g. 06:30. */
const localTime = (hourUtc: number) =>
  new Date(Date.UTC(2026, 0, 5, hourUtc)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

function Title({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-4 grid gap-1">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description && <p className="max-w-[68ch] text-[13px] text-fg-2">{description}</p>}
    </div>
  )
}

/** Each person's own: the digest, which shared entries to show, and what they follow. */
export function NotificationsSettings() {
  return (
    <section className="grid gap-8">
      <DigestSettings />
      <WatchList />
    </section>
  )
}

function DigestSettings() {
  const { data: settings, isLoading } = useInboxSettings()
  const save = useSaveInboxSettings()
  if (isLoading || !settings) return <Spinner label="Loading settings…" />
  const update = (patch: Partial<InboxSettings>) => {
    const next = { ...settings, ...patch }
    save.mutate({ digest: next.digest, digest_day: next.digest_day, muted_kinds: next.muted_kinds })
  }
  const toggleMuted = (kind: InboxSettings['muted_kinds'][number], shown: boolean) =>
    update({ muted_kinds: shown ? settings.muted_kinds.filter((k) => k !== kind) : [...settings.muted_kinds, kind] })

  return (
    <div className="grid gap-6">
      <div>
        <Title
          title="Digest"
          description={`One inbox entry that rolls up what your follows caught, updates to your maps, new maps and the top new papers. It arrives at ${localTime(settings.digest_hour_utc)} your time, and is skipped when there is nothing to say.`}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            label="Digest"
            value={settings.digest}
            options={[{ value: 'off', label: 'Off' }, { value: 'daily', label: 'Daily' }, { value: 'weekly', label: 'Weekly' }]}
            onChange={(digest) => update({ digest })}
          />
          {settings.digest === 'weekly' && (
            <label className="flex items-center gap-2 text-[13px] text-fg-2">
              on
              <select value={settings.digest_day} onChange={(e) => update({ digest_day: Number(e.target.value) })} className={cn(inputClass, 'pr-6')}>
                {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
              </select>
            </label>
          )}
          {settings.last_digest_at && <span className="text-[12px] text-fg-3">Last one {timeAgo(settings.last_digest_at)}</span>}
        </div>
      </div>
      <div>
        <Title title="Shown in the inbox" description="Updates to the maps you follow always show. These two can get busy." />
        <div className="grid gap-2">
          {MUTABLE.map((m) => {
            const shown = !settings.muted_kinds.includes(m.kind)
            return (
              <label key={m.kind} className="flex items-baseline gap-2.5 text-[13px]">
                <input type="checkbox" checked={shown} onChange={() => toggleMuted(m.kind, shown)} className="translate-y-[2px] accent-[var(--accent)]" />
                <span className="text-fg">{m.label}</span>
                <span className="text-[12px] text-fg-3">{m.note}</span>
              </label>
            )
          })}
        </div>
      </div>
      {save.error && <Notice tone="error" title="Not saved">{apiErrorMessage(save.error, 'Try again')}</Notice>}
    </div>
  )
}

function WatchList() {
  const { data, isLoading } = useWatches()
  const setDelivery = useSetDelivery()
  const unfollow = useUnfollow()
  const watches = data?.watches ?? []

  return (
    <div>
      <Title
        title="Following"
        description={<>Follow a map, a search, a source or a cluster from its page. "As it happens" gives each its own inbox entries; "Digest only" keeps them for the digest. {data && `${watches.length} of ${data.limit}.`}</>}
      />
      {isLoading ? <Spinner label="Loading…" /> : !watches.length ? (
        <Notice title="You follow nothing yet">Use the Follow button on a map, a search, a source or a cluster.</Notice>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[600px] text-left text-[13px]">
            <thead className="border-b border-line bg-surface text-[12px] text-fg-3">
              <tr>
                <th className="px-4 py-2.5 font-normal">Following</th>
                <th className="px-4 py-2.5 font-normal">Kind</th>
                <th className="px-4 py-2.5 text-right font-normal" title="Items it caught in the last 7 days">7 days</th>
                <th className="px-4 py-2.5 font-normal">News</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {watches.map((w) => (
                <tr key={w.id} className="bg-bg">
                  <td className="max-w-[320px] px-4 py-2.5">
                    <span className="flex items-center gap-2">
                      {w.link ? <Link to={w.link} className="truncate font-medium text-fg hover:underline">{w.label}</Link> : <span className="truncate font-medium text-fg">{w.label}</span>}
                      {w.status === 'retired' && <span title="Re-clustering dropped this cluster; it catches nothing now"><Chip>Retired</Chip></span>}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-fg-2">{KIND_LABEL[w.kind]}</td>
                  <td className="px-4 py-2.5 text-right font-mono tabular-nums text-fg-2">{w.kind === 'map' ? '—' : w.hits_7d}</td>
                  <td className="px-4 py-2.5">
                    <select
                      aria-label={`How news from ${w.label} arrives`}
                      value={w.delivery}
                      onChange={(e) => setDelivery.mutate({ id: w.id, delivery: e.target.value as Delivery })}
                      className={cn(inputClass, 'h-7 pr-6')}
                    >
                      <option value="instant">As it happens</option>
                      <option value="digest">Digest only</option>
                    </select>
                  </td>
                  <td className="px-2 py-2.5 text-right">
                    <Button variant="ghost" size="icon-sm" title="Stop following" aria-label={`Stop following ${w.label}`} disabled={unfollow.isPending} onClick={() => unfollow.mutate(w.id)}>
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(setDelivery.error || unfollow.error) && (
        <Notice tone="error" className="mt-3" title="Not changed">{apiErrorMessage(setDelivery.error ?? unfollow.error, 'Try again')}</Notice>
      )}
    </div>
  )
}
