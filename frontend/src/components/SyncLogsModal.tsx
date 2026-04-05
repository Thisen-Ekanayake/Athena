import React, { useEffect, useState, useRef } from 'react'
import { X, Terminal } from 'lucide-react'

interface SyncLogsModalProps {
  isOpen: boolean
  onClose: () => void
}

export function SyncLogsModal({ isOpen, onClose }: SyncLogsModalProps) {
  const [logs, setLogs] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) {
      setLogs([])
      return
    }

    const eventSource = new EventSource('http://localhost:8000/api/v1/sync/events')

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.message) {
          setLogs((prev) => [...prev, data.message].slice(-100)) // Keep last 100 logs
        }
      } catch (err) {
        console.error('Error parsing sync event:', err)
      }
    }

    eventSource.onerror = (err) => {
      console.error('EventSource failed:', err)
      // We don't automatically close on error because it might be a temporary hiccup
      // but we could add a "Connection lost" message
      setLogs((prev) => [...prev, '--- Connection lost. Reconnecting... ---'])
    }

    return () => {
      eventSource.close()
    }
  }, [isOpen])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  if (!isOpen) return null

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
            <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            <span>CONNECTED</span>
          </div>
        </div>
      </div>
    </div>
  )
}
