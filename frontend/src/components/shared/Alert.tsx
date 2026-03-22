import { AlertCircle, CheckCircle2, AlertTriangle, Info, X } from 'lucide-react'
import * as React from 'react'

interface AlertProps {
  type?: 'info' | 'success' | 'warning' | 'error'
  title?: string
  children: React.ReactNode
  onDismiss?: () => void
}

export function Alert({ type = 'info', title, children, onDismiss }: AlertProps) {
  const styles = {
    info: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    success: 'bg-green-500/10 text-green-400 border-green-500/20',
    warning: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
    error: 'bg-red-500/10 text-red-400 border-red-500/20'
  }

  const icons = {
    info: Info,
    success: CheckCircle2,
    warning: AlertTriangle,
    error: AlertCircle
  }

  const Icon = icons[type]

  return (
    <div className={`p-4 rounded-lg border flex gap-3 ${styles[type]} relative`}>
      <Icon className="w-5 h-5 shrink-0 mt-0.5" />
      <div className="flex-1">
        {title && <h4 className="font-semibold mb-1 text-sm">{title}</h4>}
        <div className="text-sm opacity-90">{children}</div>
      </div>
      {onDismiss && (
        <button 
          onClick={onDismiss}
          className="absolute top-2 right-2 p-1 hover:bg-black/20 rounded-md"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  )
}
