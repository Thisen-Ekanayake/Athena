import { Component, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error) {
    console.error('[Athena] Unhandled render error:', error)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-bg px-6 text-center">
          <AlertTriangle className="h-6 w-6 text-bad" aria-hidden="true" />
          <h2 className="text-[16px] font-semibold text-fg">Something went wrong</h2>
          <p className="max-w-sm text-[13px] text-fg-2">{this.state.error?.message ?? 'An unexpected error occurred.'}</p>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-1 h-8 rounded-lg border border-line bg-surface px-3 text-[13px] font-medium text-fg hover:border-line-strong"
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
