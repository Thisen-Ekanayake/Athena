import { useState } from 'react'
import { ChevronDown, ChevronUp, ExternalLink, BookOpen, Globe } from 'lucide-react'
import { motion } from 'framer-motion'
import type { PaperResult } from './api'

interface PaperCardProps {
  paper: PaperResult
  index?: number
}

function formatAuthors(authors: string[]): string {
  if (!authors.length) return 'Unknown authors'
  if (authors.length <= 3) return authors.join(', ')
  return `${authors.slice(0, 3).join(', ')}, et al.`
}

export function PaperCard({ paper, index = 0 }: PaperCardProps) {
  const [expanded, setExpanded] = useState(false)
  const isLocal = paper.source === 'local'

  const badgeClass = isLocal
    ? 'bg-accent-primary/15 text-accent-primary border-accent-primary/30'
    : 'bg-amber-400/10 text-amber-300 border-amber-400/30'
  const badgeLabel = isLocal ? 'Library' : 'Semantic Scholar'
  const BadgeIcon = isLocal ? BookOpen : Globe

  return (
    <motion.article
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index, 8) * 0.03 }}
      className="rounded-lg border border-border-subtle bg-glass-fill backdrop-blur-glass px-5 py-4 hover:border-border-glow transition-colors"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {paper.url ? (
            <a
              href={paper.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group inline-flex items-start gap-2 text-text-primary font-display font-semibold leading-snug hover:text-accent-primary transition-colors"
            >
              <span>{paper.title || 'Untitled'}</span>
              <ExternalLink className="w-3.5 h-3.5 mt-1 flex-shrink-0 opacity-60 group-hover:opacity-100" />
            </a>
          ) : (
            <h3 className="text-text-primary font-display font-semibold leading-snug">
              {paper.title || 'Untitled'}
            </h3>
          )}

          <p className="mt-1 text-[12px] text-text-muted">
            {formatAuthors(paper.authors)}
          </p>

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-ghost">
            {paper.year !== null && <span>{paper.year}</span>}
            {paper.citation_count !== null && paper.citation_count !== undefined && (
              <span>
                {paper.citation_count.toLocaleString()}{' '}
                {paper.citation_count === 1 ? 'citation' : 'citations'}
              </span>
            )}
            {paper.score !== null && paper.score !== undefined && (
              <span>similarity {(paper.score).toFixed(3)}</span>
            )}
          </div>
        </div>

        <span
          className={`inline-flex items-center gap-1 px-2 py-1 rounded-full border text-[10px] font-display font-medium tracking-wide whitespace-nowrap ${badgeClass}`}
        >
          <BadgeIcon className="w-3 h-3" />
          {badgeLabel}
        </span>
      </div>

      {paper.abstract && (
        <div className="mt-3">
          <p
            className={`text-[13px] text-text-secondary leading-relaxed ${
              expanded ? '' : 'line-clamp-3'
            }`}
          >
            {paper.abstract}
          </p>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-2 inline-flex items-center gap-1 text-[11px] text-text-muted hover:text-text-primary transition-colors"
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3.5 h-3.5" /> Collapse
              </>
            ) : (
              <>
                <ChevronDown className="w-3.5 h-3.5" /> Read abstract
              </>
            )}
          </button>
        </div>
      )}
    </motion.article>
  )
}
