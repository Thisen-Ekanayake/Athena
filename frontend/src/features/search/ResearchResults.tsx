import { useState } from 'react'
import { BookOpen, Check, ChevronDown, Copy, ExternalLink, Globe, Sparkles } from 'lucide-react'
import { Oracle } from '../astrolabe/Oracle'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { cn } from '../../ui/cn'
import type { PaperResult } from './api'

function authors(list: string[]) {
  if (!list.length) return 'Unknown authors'
  return list.length <= 3 ? list.join(', ') : `${list.slice(0, 3).join(', ')} et al.`
}

/** A paper from the library or from Semantic Scholar, with its abstract one click away. */
export function ResearchPaper({ paper }: { paper: PaperResult }) {
  const [open, setOpen] = useState(false)
  const local = paper.source === 'local'
  return (
    <article className="px-4 py-3.5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-medium leading-snug text-fg">
            {paper.url ? (
              <a href={paper.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                {paper.title || 'Untitled'} <ExternalLink className="mb-0.5 inline h-3 w-3 text-fg-3" aria-hidden="true" />
              </a>
            ) : (
              paper.title || 'Untitled'
            )}
          </h3>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-fg-3">
            <span className="text-fg-2">{authors(paper.authors)}</span>
            {paper.year !== null && <><span aria-hidden="true">·</span><span>{paper.year}</span></>}
            {paper.citation_count != null && <><span aria-hidden="true">·</span><span>{paper.citation_count.toLocaleString()} citations</span></>}
          </p>
        </div>
        <Chip tone={local ? 'accent' : 'neutral'}>
          {local ? <BookOpen aria-hidden="true" /> : <Globe aria-hidden="true" />} {local ? 'Your library' : 'Semantic Scholar'}
        </Chip>
      </div>
      {paper.abstract && (
        <>
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mt-1.5 inline-flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg">
            {open ? 'Hide the abstract' : 'Read the abstract'} <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
          </button>
          {open && <p className="mt-1.5 text-[13.5px] leading-relaxed text-fg-2">{paper.abstract}</p>}
        </>
      )}
    </article>
  )
}

/** The AI-written literature review. The oracle and the moving border show while it is being written. */
export function LitReview({ query, review, pending }: { query: string; review: string | null; pending: boolean }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    if (!review) return
    try {
      await navigator.clipboard.writeText(review)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard unavailable; the text can still be selected.
    }
  }

  return (
    <section className="relative rounded-xl border border-line bg-surface">
      <span className="ai-ring" data-active={pending} aria-hidden="true" />
      <header className="flex items-center gap-3 px-4 pt-4">
        <Oracle mode={pending ? 'thinking' : 'done'} size={52} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-fg">Literature review</h2>
          <p className="truncate text-[12.5px] text-fg-3" aria-live="polite">
            {pending ? <span className="font-myth text-[14px] text-fg-2">Consulting the oracle…</span> : <>On “{query}”, written by AI from the papers below</>}
          </p>
        </div>
        {review && (
          <Button variant="secondary" size="sm" onClick={copy}>
            {copied ? <><Check /> Copied</> : <><Copy /> Copy</>}
          </Button>
        )}
      </header>
      <div className="px-4 pt-3 pb-4">
        {pending ? (
          <p className="text-[13.5px] text-fg-3">Reading the papers and writing the review. This can take a minute.</p>
        ) : review ? (
          <div className="max-w-[72ch] text-[14px] leading-relaxed whitespace-pre-wrap text-fg-2">{review}</div>
        ) : (
          <p className="flex items-center gap-1.5 text-[13.5px] text-fg-3"><Sparkles className="h-3.5 w-3.5" /> No review was written for this search.</p>
        )}
      </div>
    </section>
  )
}
