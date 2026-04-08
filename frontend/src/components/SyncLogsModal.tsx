import { useEffect, useState, useRef } from 'react'
import { X, Terminal, CheckCircle, AlertCircle, AlertTriangle } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface SyncLogsModalProps {
  isOpen: boolean
  onClose: () => void
}

interface SyncState {
  total: number
  completed: number
  errors: number
  status: null | 'done' | 'partial' | 'error'
}

const INITIAL_SYNC_STATE: SyncState = { total: 0, completed: 0, errors: 0, status: null }

export function SyncLogsModal({ isOpen, onClose }: SyncLogsModalProps) {
  const [logs, setLogs] = useState<string[]>([])
  const [syncState, setSyncState] = useState<SyncState>(INITIAL_SYNC_STATE)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) {
      setLogs([])
      setSyncState(INITIAL_SYNC_STATE)
      return
    }

    const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'
    const eventSource = new EventSource(`${baseUrl}/sync/events`)

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (!data.message) return

        let structured: any = null
        try { structured = JSON.parse(data.message) } catch { /* not structured */ }

        if (structured?.type === 'sync_start') {
          setSyncState({ total: structured.total, completed: 0, errors: 0, status: null })
        } else if (structured?.type === 'sync_progress') {
          setSyncState(prev => ({ ...prev, completed: structured.completed, total: structured.total }))
        } else if (structured?.type === 'sync_done') {
          setSyncState({ total: structured.total, completed: structured.completed, errors: structured.errors, status: structured.status })
        } else {
          setLogs(prev => [...prev, data.message].slice(-100))
        }
      } catch (err) {
        console.error('Error parsing sync event:', err)
      }
    }

    eventSource.onerror = () => {
      setLogs(prev => [...prev, '--- Connection lost. Reconnecting... ---'])
    }

    return () => eventSource.close()
  }, [isOpen])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  if (!isOpen) return null

  const progress = syncState.total > 0 ? (syncState.completed / syncState.total) * 100 : 0
  const isDone = syncState.status !== null
  const succeeded = syncState.completed - syncState.errors

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden animate-in fade-in zoom-in duration-200">

        <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-900/50">
          <div className="flex items-center gap-2">
            <Terminal className="w-5 h-5 text-accent-primary" />
            <h3 className="text-sm font-display font-semibold text-slate-200 uppercase tracking-wider">
              Live Sync Output
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-800 rounded-md transition-colors text-slate-400 hover:text-slate-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {syncState.total > 0 && (
          <div className="px-4 pt-3 pb-2 bg-slate-900/50 border-b border-slate-800 space-y-1.5">
            <div className="flex justify-between items-center text-[11px] font-mono text-slate-400">
              <span>Sources synced</span>
              <span>{syncState.completed} / {syncState.total}</span>
            </div>
            <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
              <motion.div
                className={`h-full rounded-full ${
                  syncState.status === 'error' ? 'bg-red-500' :
                  syncState.status === 'partial' ? 'bg-yellow-500' :
                  syncState.status === 'done' ? 'bg-green-500' :
                  'bg-accent-primary'
                }`}
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.4, ease: 'easeOut' }}
              />
            </div>
          </div>
        )}

        <AnimatePresence>
          {isDone && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className={`px-4 py-3 flex items-center gap-2 text-sm font-medium border-b ${
                syncState.status === 'done'
                  ? 'bg-green-500/10 text-green-400 border-green-500/20'
                  : syncState.status === 'partial'
                  ? 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20'
                  : 'bg-red-500/10 text-red-400 border-red-500/20'
              }`}
            >
              {syncState.status === 'done' && <CheckCircle className="w-4 h-4 shrink-0" />}
              {syncState.status === 'partial' && <AlertTriangle className="w-4 h-4 shrink-0" />}
              {syncState.status === 'error' && <AlertCircle className="w-4 h-4 shrink-0" />}
              <span>
                {syncState.status === 'done' &&
                  `Sync complete — all ${syncState.total} sources updated successfully.`}
                {syncState.status === 'partial' &&
                  `Sync complete — ${succeeded} of ${syncState.total} sources succeeded, ${syncState.errors} failed.`}
                {syncState.status === 'error' &&
                  `Sync failed — all ${syncState.total} sources encountered errors.`}
              </span>
            </motion.div>
          )}
        </AnimatePresence>

        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto p-4 font-mono text-[12px] leading-relaxed text-slate-300 bg-black/40 custom-scrollbar"
        >
          {logs.length === 0 ? (
            <div className="flex items-center justify-center h-full text-slate-500 italic">
              Connecting to sync stream...
            </div>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="mb-0.5 border-l border-slate-800 pl-3">
                <span className="text-slate-500 mr-2">[{i}]</span>
                <span className={
                  log.includes('ERROR') ? 'text-red-400' :
                  log.includes('WARNING') ? 'text-yellow-400' :
                  log.includes('INFO') ? 'text-blue-300' : ''
                }>
                  {log}
                </span>
              </div>
            ))
          )}
        </div>

        <div className="p-3 border-t border-slate-800 bg-slate-900/50 text-[10px] text-slate-500 flex justify-between items-center px-4">
          <span>Streaming live from Athena Sync Engine</span>
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${isDone ? 'bg-slate-500' : 'bg-green-500 animate-pulse'}`} />
            <span>{isDone ? 'IDLE' : 'CONNECTED'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
