import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Loader2, Search } from 'lucide-react'
import { motion } from 'framer-motion'
import { searchPapers, type SearchResponse } from './api'
import { PaperCard } from './PaperCard'
import { LitReview } from './LitReview'

export function SearchPanel() {
  const [query, setQuery] = useState('')
  const [generateReview, setGenerateReview] = useState(true)

  const mutation = useMutation<SearchResponse, Error, { query: string; generateReview: boolean }>({
    mutationFn: ({ query, generateReview }) => searchPapers(query, undefined, generateReview),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = query.trim()
    if (trimmed.length < 3) return
    mutation.mutate({ query: trimmed, generateReview })
  }

  const results = mutation.data
  const isLoading = mutation.isPending
  const error = mutation.error

  return (
    <div className="flex flex-col gap-8 max-w-[1100px] mx-auto">
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-accent-primary/15 border border-accent-primary/30 flex items-center justify-center text-accent-primary shadow-[0_0_15px_rgba(76,95,255,0.2)]">
            <Search className="w-4 h-4" />
          </div>
          <h1 className="text-3xl font-display font-bold tracking-tight text-text-primary">
            Research <span className="text-accent-primary">Search</span>
          </h1>
        </div>
        <p className="text-sm text-text-muted max-w-2xl">
          Search your indexed library and Semantic Scholar together, then generate a structured
          literature review on the fly.
        </p>
      </header>

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="flex items-stretch gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-ghost pointer-events-none" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. retrieval-augmented generation for code"
              minLength={3}
              maxLength={500}
              className="w-full pl-10 pr-3 py-3 rounded-lg border border-border-subtle bg-glass-fill backdrop-blur-glass text-text-primary placeholder:text-text-ghost focus:outline-none focus:border-accent-primary/60 focus:ring-1 focus:ring-accent-primary/30 transition-colors"
            />
          </div>
          <button
            type="submit"
            disabled={isLoading || query.trim().length < 3}
            className="px-5 py-3 rounded-lg bg-accent-primary text-white font-display font-medium text-sm shadow-[0_0_18px_rgba(76,95,255,0.35)] hover:bg-accent-primary/90 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2 transition-colors"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Searching…
              </>
            ) : (
              <>Search</>
            )}
          </button>
        </div>
        <label className="inline-flex items-center gap-2 text-[12px] text-text-muted select-none">
          <input
            type="checkbox"
            checked={generateReview}
            onChange={(e) => setGenerateReview(e.target.checked)}
            className="accent-accent-primary"
          />
          Generate a literature review with the results
        </label>
      </form>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-300">
          Search failed: {error.message}
        </div>
      )}

      {results && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col gap-6"
        >
          <div className="text-[12px] text-text-muted">
            <span className="text-text-primary font-medium">
              {results.papers.length}
            </span>{' '}
            {results.papers.length === 1 ? 'paper' : 'papers'} found ·{' '}
            <span className="text-text-secondary">{results.local_count} from your library</span> ·{' '}
            <span className="text-text-secondary">{results.live_count} from Semantic Scholar</span>
          </div>

          {results.papers.length > 0 ? (
            <div className="grid gap-3">
              {results.papers.map((paper, idx) => (
                <PaperCard key={paper.id || `${paper.source}-${idx}`} paper={paper} index={idx} />
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-border-subtle bg-glass-fill px-5 py-8 text-center text-sm text-text-muted">
              No papers found for "{results.query}". Try a broader query.
            </div>
          )}

          {results.lit_review && (
            <LitReview query={results.query} review={results.lit_review} />
          )}
        </motion.div>
      )}
    </div>
  )
}
