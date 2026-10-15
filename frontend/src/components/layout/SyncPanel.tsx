import { useState } from 'react'
import { isAxiosError } from 'axios'
import { RefreshCw, X } from 'lucide-react'
import { useIsAdmin } from '../../api/queries/auth'
import { isFinished, isRunning, useStartSync, useSyncStatus, type SyncStatus } from '../../api/queries/sync'
import { useSyncUi } from '../../store/syncStore'
import { cn } from '../../ui/cn'
import { barClass, etaText, resultClass, shortAgo, syncResult, useLastSynced, useNow } from './syncFormat'

function Bar({ status, className }: { status: SyncStatus; className?: string }) {
  const pct = isRunning(status) ? status.percent ?? 0 : 100
  return (
    <div
      className={cn('h-1.5 overflow-hidden rounded-full bg-surface-3', className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-label="Sync progress"
    >
      <div className={cn('h-full rounded-full transition-[width] duration-700 ease-out', barClass(status))} style={{ width: `${pct}%` }} />
    </div>
  )
}

/** Starts a sync and opens its dialog; when one is running already, opens that one. */
function useSyncAction() {
  const start = useStartSync()
  const openDialog = useSyncUi((s) => s.openDialog)
  const [error, setError] = useState<string | null>(null)
  const run = (status: SyncStatus | undefined) => {
    setError(null)
    if (isRunning(status)) return openDialog()
    start.mutate(undefined, {
      onSuccess: () => openDialog(),
      onError: (e) => {
        if (isAxiosError(e) && e.response?.status === 409) openDialog()
        else setError(isAxiosError(e) && e.response?.data?.detail ? String(e.response.data.detail) : 'The sync could not start')
      },
    })
  }
  return { run, starting: start.isPending, error }
}

/**
 * The sidebar's sync control, above "Look": a Sync button with when the feed last synced; while a sync
 * runs, its percent, time left and a green bar; when it ends, the result with its log until dismissed.
 * Accounts that are not admins see the status without the button or the log.
 */
export function SyncPanel({ compact }: { compact: boolean }) {
  const admin = useIsAdmin()
  const { data: status } = useSyncStatus()
  const { run, starting, error } = useSyncAction()
  const openDialog = useSyncUi((s) => s.openDialog)
  const dismissedId = useSyncUi((s) => s.dismissedId)
  const dismiss = useSyncUi((s) => s.dismiss)
  const now = useNow()
  const lastSynced = useLastSynced(status)
  const running = isRunning(status)
  const result = isFinished(status) && status!.id !== dismissedId ? status! : null
  const ago = lastSynced ? shortAgo(lastSynced, now) : null

  const button = admin && (
    <button
      type="button"
      onClick={() => run(status)}
      disabled={starting}
      title={running ? 'Show the sync' : 'Fetch new items from every source'}
      className={cn(
        'flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-60',
        compact && 'max-lg:h-8 max-lg:w-8 max-lg:justify-center max-lg:px-0',
      )}
    >
      <RefreshCw className={cn('h-3.5 w-3.5', (running || starting) && 'animate-spin')} aria-hidden="true" />
      <span className={cn(compact && 'max-lg:sr-only')}>Sync</span>
    </button>
  )

  return (
    <div className={cn('grid min-w-0 grid-cols-1 gap-1.5 px-2.5', compact && 'max-lg:px-0')}>
      {running && status ? (
        <div
          role={admin ? 'button' : undefined}
          tabIndex={admin ? 0 : undefined}
          onClick={admin ? openDialog : undefined}
          onKeyDown={admin ? (e) => (e.key === 'Enter' || e.key === ' ') && openDialog() : undefined}
          title={admin ? 'Show the sync and its log' : undefined}
          className={cn('grid min-w-0 grid-cols-1 gap-1.5 rounded-lg py-1', admin && 'cursor-pointer')}
        >
          <div className={cn('flex items-baseline justify-between gap-2 text-[12px]', compact && 'max-lg:hidden')}>
            <span className="flex items-center gap-1.5 text-fg-2">
              <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" />
              Syncing <span className="font-mono text-fg tabular-nums">{Math.round(status.percent ?? 0)}%</span>
            </span>
            <span className="truncate text-fg-3 tabular-nums">{etaText(status)}</span>
          </div>
          {compact && <span className="hidden justify-center max-lg:flex">{button}</span>}
          <Bar status={status} className={cn(compact && 'max-lg:mx-auto max-lg:w-8')} />
        </div>
      ) : result ? (
        <div className="grid min-w-0 grid-cols-1 gap-1.5 py-1">
          <div className={cn('flex items-center justify-between gap-2 text-[12px]', compact && 'max-lg:hidden')}>
            <span className={cn('min-w-0 truncate', resultClass(result))} title={syncResult(result)}>
              {syncResult(result)}
            </span>
            <button type="button" onClick={() => dismiss(result.id!)} aria-label="Dismiss the sync result" title="Dismiss" className="-mr-1 rounded p-0.5 text-fg-3 hover:bg-surface-2 hover:text-fg">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <Bar status={result} className={cn(compact && 'max-lg:mx-auto max-lg:w-8')} />
          <div className={cn('flex items-center justify-between gap-2 text-[12px]', compact && 'max-lg:justify-center')}>
            {admin && (
              <button type="button" onClick={openDialog} className={cn('text-fg-2 underline-offset-2 hover:text-fg hover:underline', compact && 'max-lg:hidden')}>
                View log
              </button>
            )}
            {button}
          </div>
        </div>
      ) : (
        <div className={cn('flex items-center justify-between gap-2', compact && 'max-lg:justify-center', !admin && 'py-1')}>
          {ago && <span className={cn('truncate text-[12px] text-fg-3', compact && 'max-lg:sr-only')} title={lastSynced ? new Date(lastSynced).toLocaleString() : undefined}>Synced {ago}</span>}
          {button}
        </div>
      )}
      {error && <p className={cn('text-[12px] text-bad', compact && 'max-lg:hidden')}>{error}</p>}
    </div>
  )
}
