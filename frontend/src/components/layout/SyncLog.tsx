import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, XCircle, X } from 'lucide-react'
import { API_BASE } from '../../api/client'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'

interface Progress {
  total: number
  completed: number
  errors: number
  status: null | 'done' | 'partial' | 'error'
}

interface SyncMessage {
  type?: 'sync_start' | 'sync_progress' | 'sync_done'
  total?: number
  completed?: number
  errors?: number
  status?: Progress['status']
}

/** Live output of a sync: a progress bar over all sources and the raw log lines. Connects while mounted. */
export function SyncLog({ className }: { className?: string }) {
  const [lines, setLines] = useState<string[]>([])
  const [progress, setProgress] = useState<Progress>({ total: 0, completed: 0, errors: 0, status: null })
  const [connected, setConnected] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/sync/events`, { withCredentials: true })
    source.onopen = () => setConnected(true)
    source.onmessage = (event) => {
      let data: { message?: string }
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      if (!data.message) return
      let msg: SyncMessage | null = null
      try {
        msg = JSON.parse(data.message)
      } catch {
        // A plain log line.
      }
      if (msg?.type === 'sync_start') setProgress({ total: msg.total ?? 0, completed: 0, errors: 0, status: null })
      else if (msg?.type === 'sync_progress') setProgress((p) => ({ ...p, completed: msg.completed ?? p.completed, total: msg.total ?? p.total }))
      else if (msg?.type === 'sync_done') setProgress({ total: msg.total ?? 0, completed: msg.completed ?? 0, errors: msg.errors ?? 0, status: msg.status ?? 'done' })
      else setLines((prev) => [...prev, data.message!].slice(-200))
    }
    source.onerror = () => setConnected(false)
    return () => source.close()
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const pct = progress.total > 0 ? (progress.completed / progress.total) * 100 : 0
  const ok = progress.completed - progress.errors

  return (
    <div className={cn('grid gap-3', className)}>
      {progress.total > 0 && (
        <div className="grid gap-1.5">
          <div className="flex justify-between text-[12px] text-fg-2">
            <span>Sources synced</span>
            <span className="font-mono tabular-nums">{progress.completed} / {progress.total}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
            <div
              className={cn('h-full rounded-full transition-[width] duration-300', progress.status === 'error' ? 'bg-bad' : progress.status === 'partial' ? 'bg-warn' : progress.status === 'done' ? 'bg-good' : 'bg-accent')}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}
      {progress.status && (
        <p className={cn('flex items-center gap-2 text-[13px]', progress.status === 'done' ? 'text-good' : progress.status === 'partial' ? 'text-warn' : 'text-bad')}>
          {progress.status === 'done' && <><CheckCircle2 className="h-4 w-4" /> All {progress.total} sources updated.</>}
          {progress.status === 'partial' && <><AlertTriangle className="h-4 w-4" /> {ok} of {progress.total} sources updated; {progress.errors} failed. Their errors are in the log below.</>}
          {progress.status === 'error' && <><XCircle className="h-4 w-4" /> Every source failed. Check the log below and the worker.</>}
        </p>
      )}
      <div ref={scrollRef} className="h-72 overflow-y-auto rounded-lg border border-line bg-bg p-3 font-mono text-[12px] leading-relaxed text-fg-2">
        {lines.length === 0 ? (
          <p className="text-fg-3">{connected ? 'Waiting for the next sync…' : 'Connecting to the sync log…'}</p>
        ) : (
          lines.map((line, i) => (
            <div key={i} className={cn(line.includes('ERROR') ? 'text-bad' : line.includes('WARNING') ? 'text-warn' : '')}>{line}</div>
          ))
        )}
      </div>
      <p className="flex items-center gap-2 text-[11.5px] text-fg-3">
        <span className={cn('h-1.5 w-1.5 rounded-full', connected ? 'bg-good' : 'bg-fg-3')} />
        {connected ? 'Live' : 'Not connected'}
      </p>
    </div>
  )
}

export function SyncDialog({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-bg/60 p-4 backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="sync-title" className="w-full max-w-2xl rounded-xl border border-line bg-surface p-5 shadow-pop">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="sync-title" className="text-[15px] font-semibold">Syncing sources</h2>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close"><X /></Button>
        </div>
        <SyncLog />
      </div>
    </div>
  )
}
