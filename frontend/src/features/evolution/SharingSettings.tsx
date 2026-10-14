import { Link } from 'react-router-dom'
import { Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { timeAgo } from '../../components/items/format'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { shareExpiry, shareUrl, useRevokeShare, useSetSharing, useShares, useSharing } from './api'
import { CopyLink } from './ShareMenu'

/** Admins: switch every share link on or off at once, and see or revoke any of them. */
export function SharingSettings() {
  const sharing = useSharing()
  const setSharing = useSetSharing()
  const shares = useShares(undefined)
  const revoke = useRevokeShare()
  const enabled = !!sharing.data
  const links = shares.data?.shares ?? []

  return (
    <section className="grid gap-6">
      <div className="mb-1 grid gap-1">
        <h2 className="text-[16px] font-semibold text-fg">Sharing</h2>
        <p className="max-w-[68ch] text-[13px] text-fg-2">
          Anyone with an account can make a read-only link to a map, from the map's Share button. People who open it
          see the map, its reading path, open problems, people and changes, without an account. Switching sharing off
          stops every link at once; they work again when it is switched back on.
        </p>
      </div>
      <label className="flex items-center gap-3 text-[13px]">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          disabled={sharing.isLoading || setSharing.isPending}
          onClick={() => setSharing.mutate(!enabled)}
          className={cn('relative h-[18px] w-[30px] rounded-full transition-colors', enabled ? 'bg-accent' : 'bg-line-strong')}
        >
          <span className={cn('absolute top-[2px] left-[2px] h-[14px] w-[14px] rounded-full bg-fg shadow transition-transform', enabled && 'translate-x-[12px]')} />
        </button>
        <span className="text-fg">{enabled ? 'Maps can be shared' : 'Sharing is off'}</span>
      </label>
      {(setSharing.error || revoke.error) && <Notice tone="error">{apiErrorMessage(setSharing.error ?? revoke.error, 'That did not work')}</Notice>}
      <div className="grid gap-2">
        <h3 className="text-[13px] font-medium text-fg">Active links</h3>
        {shares.isLoading ? <Spinner label="Loading the links…" /> : links.length === 0 ? (
          <p className="text-[13px] text-fg-3">No map has been shared yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[640px] text-left text-[13px]">
              <thead className="border-b border-line bg-surface text-[12px] text-fg-3">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Map</th>
                  <th className="px-4 py-2.5 font-medium">Made by</th>
                  <th className="px-4 py-2.5 font-medium">Views</th>
                  <th className="px-4 py-2.5 font-medium">Expiry</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {links.map((s) => (
                  <tr key={s.id} className={cn('border-b border-line last:border-0', !enabled && 'opacity-60')}>
                    <td className="px-4 py-3">
                      {s.topic && <Link to={`/evolution/${s.topic.slug}`} className="text-fg hover:underline">{s.topic.name}</Link>}
                      <p className="max-w-[260px] truncate font-mono text-[11.5px] text-fg-3">{shareUrl(s.token).replace(/^https?:\/\//, '')}</p>
                    </td>
                    <td className="px-4 py-3 text-fg-2">
                      {s.creator ?? 'Someone'}
                      <p className="text-[12px] text-fg-3">{timeAgo(s.created_at)}</p>
                    </td>
                    <td className="px-4 py-3 text-fg-2 tabular-nums">
                      {s.views}
                      {s.last_viewed_at && <p className="text-[12px] text-fg-3">last {timeAgo(s.last_viewed_at)}</p>}
                    </td>
                    <td className="px-4 py-3 text-fg-2">{shareExpiry(s)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <CopyLink token={s.token} />
                        <Button variant="ghost" size="icon-sm" onClick={() => revoke.mutate(s.id)} disabled={revoke.isPending} aria-label={`Revoke the link to ${s.topic?.name ?? 'the map'}`} title="Revoke: the link stops working">
                          <Trash2 />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
