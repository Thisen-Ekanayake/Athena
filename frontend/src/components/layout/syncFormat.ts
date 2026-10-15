import { useEffect, useState } from 'react'
import { useSources } from '../../api/queries/sources'
import type { SyncStatus } from '../../api/queries/sync'

/** "just now", "4m ago", "3h ago", "2d ago" */
export function shortAgo(ms: number, now: number): string {
  const s = Math.max(0, (now - ms) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

/** "45s", "1m 20s", "12m" */
export function formatEta(seconds: number): string {
  const s = Math.max(1, Math.round(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return m < 10 && s % 60 ? `${m}m ${s % 60}s` : `${Math.round(s / 60)}m`
}

/** The clock, ticking every ``ms``, so "4m ago" and retry countdowns stay current. */
export function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

/** When the feed last synced: the latest sync's end, else the newest fetch of any source. */
export function useLastSynced(status: SyncStatus | undefined): number | null {
  const { data: sources } = useSources()
  if (status?.finished_at) return status.finished_at * 1000
  const latest = sources
    ?.map((s) => s.last_fetched_at)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1)
  return latest ? new Date(latest).getTime() : null
}

/** What a finished sync came to, in a few words. */
export function syncResult(s: SyncStatus): string {
  const fresh = s.new_items ? `${s.new_items} new` : 'nothing new'
  if (s.state === 'stalled') return 'Sync stopped responding'
  if (s.state === 'error') return 'Sync failed'
  if (s.state === 'partial') {
    const problems = [s.errors && `${s.errors} failed`, s.empty && `${s.empty} found nothing`].filter(Boolean).join(', ')
    return `Synced · ${fresh} · ${problems}`
  }
  return `Sync complete · ${fresh}`
}

/** The bar's colour: green while running and when no source failed (one that found nothing is only a note). */
export function barClass(s: SyncStatus): string {
  if (s.state === 'error') return 'bg-bad'
  return s.state === 'stalled' || (s.errors ?? 0) > 0 ? 'bg-warn' : 'bg-good'
}

/** The result's text colour, matching the bar. */
export function resultClass(s: SyncStatus): string {
  if (s.state === 'error') return 'text-bad'
  return s.state === 'stalled' || (s.errors ?? 0) > 0 ? 'text-warn' : 'text-good'
}

/** Time left, or why there is none: the worker has not started, too early to tell, or a source runs long. */
export function etaText(s: SyncStatus, long = false): string {
  if (s.waiting_for_worker) return long ? 'Waiting for the worker to pick it up…' : 'Waiting for the worker'
  if (s.eta_seconds != null) return long ? `About ${formatEta(s.eta_seconds)} left` : `ETA ${formatEta(s.eta_seconds)}`
  if ((s.percent ?? 0) >= 90) return 'Finishing…'
  return long ? 'Estimating time left…' : 'Estimating…'
}
