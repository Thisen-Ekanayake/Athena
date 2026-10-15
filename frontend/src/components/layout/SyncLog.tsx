import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, CircleDashed, Clock, RefreshCw, X, XCircle } from 'lucide-react'
import { fetchSyncLog, isRunning, useSyncStatus, type SyncLogLine, type SyncSource, type SyncStatus } from '../../api/queries/sync'
import { useSyncUi } from '../../store/syncStore'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'
import { barClass, etaText, formatEta, syncResult, useNow } from './syncFormat'

/**
 * The latest sync's log, polled while shown: new lines every second while the sync runs, and a look every
 * few seconds otherwise, to catch the next one. The status that comes with them also refreshes the sidebar.
 */
function useSyncLog() {
  const queryClient = useQueryClient()
  const [lines, setLines] = useState<SyncLogLine[]>([])
  const [failed, setFailed] = useState(false)
  const seq = useRef(0)
  const syncId = useRef<string | undefined>(undefined)

  useEffect(() => {
    let dead = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const status = await fetchSyncLog(seq.current)
        if (dead) return
        setFailed(false)
        if (status.id !== syncId.current) {
          // Another sync: start its log from the top
          const restart = syncId.current !== undefined && seq.current > 0
          syncId.current = status.id
          seq.current = 0
          setLines([])
          if (restart) return void (timer = setTimeout(tick, 0))
        }
        const fresh = status.log ?? []
        if (fresh.length) {
          seq.current = fresh[fresh.length - 1].seq
          setLines((prev) => [...prev, ...fresh].slice(-1000))
        }
        const { log: _log, ...rest } = status // eslint-disable-line @typescript-eslint/no-unused-vars
        queryClient.setQueryData(['sync', 'status'], rest)
        timer = setTimeout(tick, isRunning(status) ? 1000 : 5000)
      } catch {
        if (dead) return
        setFailed(true)
        timer = setTimeout(tick, 3000)
      }
    }
    tick()
    return () => {
      dead = true
      clearTimeout(timer)
    }
  }, [queryClient])

  return { lines, failed }
}

const SOURCE_STATE: Record<SyncSource['state'], { icon: typeof Clock; className: string; label: string }> = {
  queued: { icon: CircleDashed, className: 'text-fg-3', label: 'Waiting' },
  running: { icon: RefreshCw, className: 'text-fg-2 [&>svg]:animate-spin', label: 'Fetching' },
  retrying: { icon: Clock, className: 'text-warn', label: 'Retrying' },
  done: { icon: CheckCircle2, className: 'text-good', label: 'Done' },
  empty: { icon: AlertTriangle, className: 'text-warn', label: 'Found nothing' },
  error: { icon: XCircle, className: 'text-bad', label: 'Failed' },
}

function SourceRow({ source, now }: { source: SyncSource; now: number }) {
  const { icon: Icon, className, label } = SOURCE_STATE[source.state]
  let detail = label
  if (source.state === 'done') detail = source.new ? `+${source.new} new` : 'Nothing new'
  if (source.state === 'retrying' && source.retry_at) {
    const wait = source.retry_at - now / 1000
    detail = wait > 1 ? `Retrying in ${formatEta(wait)}` : 'Retrying'
  }
  return (
    <li className="flex min-w-0 items-center gap-2 text-[12.5px]" title={source.error ?? undefined}>
      <span className={cn('flex shrink-0', className)}><Icon className="h-3.5 w-3.5" aria-hidden="true" /></span>
      <span className="min-w-0 flex-1 truncate text-fg-2">{source.name}</span>
      <span className={cn('shrink-0 text-[12px]', source.state === 'done' ? 'text-fg-3' : className)}>{detail}</span>
    </li>
  )
}

function Progress({ status }: { status: SyncStatus }) {
  const running = isRunning(status)
  const pct = running ? status.percent ?? 0 : 100
  return (
    <div className="grid gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[22px] font-medium text-fg tabular-nums">{Math.round(pct)}%</span>
        <span className="text-[12.5px] text-fg-3 tabular-nums">
          {running
            ? etaText(status, true)
            : status.finished_at && status.started_at
              ? `Took ${formatEta(status.finished_at - status.started_at)}`
              : null}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label="Sync progress">
        <div className={cn('h-full rounded-full transition-[width] duration-700 ease-out', barClass(status))} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-[12.5px] text-fg-3">
        {status.completed} of {status.total} sources · {status.new_items ? `${status.new_items} new items` : 'no new items yet'}
      </p>
    </div>
  )
}

/** The latest sync as it happens: progress, each source's state and the log (admins). */
export function SyncLog({ className }: { className?: string }) {
  const { data: status } = useSyncStatus()
  const { lines, failed } = useSyncLog()
  const now = useNow(1000)
  const scrollRef = useRef<HTMLDivElement>(null)
  const running = isRunning(status)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  return (
    <div className={cn('grid gap-4', className)}>
      {status && status.state !== 'idle' ? <Progress status={status} /> : <p className="text-[13px] text-fg-3">No sync has run today.</p>}
      {status?.state === 'stalled' && (
        <p className="flex items-center gap-2 text-[13px] text-warn">
          <AlertTriangle className="h-4 w-4 shrink-0" /> No source has reported for a while. Check that the worker is running, then sync again.
        </p>
      )}
      {!!status?.sources?.length && (
        <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2" aria-label="Sources">
          {status.sources.map((s) => <SourceRow key={s.id} source={s} now={now} />)}
        </ul>
      )}
      <div ref={scrollRef} className="h-64 shrink-0 overflow-y-auto rounded-lg border border-line bg-bg p-3 font-mono text-[12px] leading-relaxed text-fg-2">
        {lines.length === 0 ? (
          <p className="text-fg-3">{failed ? 'Could not load the log.' : running ? 'Waiting for the first lines…' : 'No log for this sync.'}</p>
        ) : (
          lines.map((l) => (
            <div key={l.seq} className={cn('break-words', l.line.includes('| ERROR') || l.line.includes('| CRITICAL') ? 'text-bad' : l.line.includes('| WARNING') ? 'text-warn' : l.line.includes('| SUCCESS') ? 'text-good' : '')}>
              {l.line}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

/** The latest sync's progress, sources and log, centred over the page. Closing it leaves the sync running. */
export function SyncDialog() {
  const open = useSyncUi((s) => s.dialogOpen)
  const close = useSyncUi((s) => s.closeDialog)
  const { data: status } = useSyncStatus()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, close])

  if (!open) return null
  const running = isRunning(status)
  const finished = status && !running && status.state !== 'idle'

  // In a portal: inside the sticky, backdrop-blurred top bar, "fixed" was relative to the bar, not the window.
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-bg/60 p-4 backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div role="dialog" aria-modal="true" aria-labelledby="sync-title" className="flex max-h-[calc(100vh-2rem)] w-full max-w-2xl flex-col rounded-xl border border-line bg-surface shadow-pop">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 id="sync-title" className="text-[15px] font-semibold">
            {running ? 'Syncing sources' : finished ? syncResult(status) : 'Sync'}
          </h2>
          <Button variant="ghost" size="icon-sm" onClick={close} aria-label="Close"><X /></Button>
        </div>
        <SyncLog className="min-h-0 overflow-y-auto px-5 py-4" />
        <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
          <p className="text-[12px] text-fg-3">
            {running ? 'The sync keeps going if you close this; its progress shows in the sidebar.' : 'The log is kept for a day.'}
          </p>
          <Button variant={running ? 'primary' : 'secondary'} size="sm" onClick={close}>
            {running ? 'Run in background' : 'Close'}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
