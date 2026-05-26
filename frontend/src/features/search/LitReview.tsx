import { useState } from 'react'
import { Check, Copy, FileText } from 'lucide-react'

interface LitReviewProps {
  query: string
  review: string
}

export function LitReview({ query, review }: LitReviewProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(review)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard unavailable — ignore
    }
  }

  return (
    <section className="rounded-lg border border-border-subtle bg-glass-fill backdrop-blur-glass">
      <header className="flex items-center justify-between gap-4 px-5 py-4 border-b border-border-subtle">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-7 h-7 rounded-md bg-accent-primary/15 border border-accent-primary/30 flex items-center justify-center text-accent-primary">
            <FileText className="w-3.5 h-3.5" />
          </div>
          <h2 className="text-base font-display font-semibold text-text-primary truncate">
            Literature Review: <span className="text-accent-primary">{query}</span>
          </h2>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-border-subtle text-[12px] text-text-muted hover:text-text-primary hover:border-border-glow transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" /> Copied
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" /> Copy
            </>
          )}
        </button>
      </header>

      <div className="px-5 py-4">
        <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-relaxed text-text-secondary">
          {review}
        </pre>
      </div>
    </section>
  )
}
