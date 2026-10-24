import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Check, Copy, GitBranch, RotateCcw, Sparkles, Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { isWriting, useDeleteReview, useReview, useStartReview, type Review, type ReviewSource } from '../../api/queries/reviews'
import { DownloadMenu } from '../../components/DownloadMenu'
import { timeAgo } from '../../components/items/format'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { Oracle } from '../astrolabe/Oracle'
import { Markdown } from './Markdown'
import { AddToProjectMenu } from '../projects/AddToProjectMenu'

/** Where a review comes from: a research map, or only search results' abstracts. */
export function ReviewSourceChip({ review }: { review: Pick<Review, 'mode' | 'topic'> }) {
  if (review.mode === 'map' && review.topic) {
    return (
      <Link to={`/evolution/${review.topic.slug}`} title="Grounded in this map: its eras, milestones, open problems and the papers' own text">
        <Chip tone="accent"><GitBranch aria-hidden="true" />From the map {review.topic.name}</Chip>
      </Link>
    )
  }
  return <span title="No research map covers this query, so it was written from search results' abstracts"><Chip tone="warn">From abstracts only</Chip></span>
}

function fileName(title: string) {
  return title.normalize('NFKD').replace(/[^\w]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase().slice(0, 80) || 'review'
}

function Reference({ source }: { source: ReviewSource }) {
  const authors = source.authors.slice(0, 3).join(', ') + (source.authors.length > 3 ? ' et al.' : '')
  const link = source.url || (source.doi ? `https://doi.org/${source.doi}` : null)
  return (
    <li id={`ref-${source.n}`} className="flex gap-2 scroll-mt-24 text-[13px] leading-relaxed target:rounded target:bg-accent-soft">
      <span className="shrink-0 font-mono text-[12px] text-fg-3 tabular-nums">[{source.n}]</span>
      <span className="text-fg-2">
        {authors && <>{authors} </>}({source.year ?? 'n.d.'}).{' '}
        {link ? <a href={link} target="_blank" rel="noopener noreferrer" className="font-medium text-fg hover:underline">{source.title}</a> : <span className="font-medium text-fg">{source.title}</span>}
        {source.venue && <>. {source.venue}</>}
      </span>
    </li>
  )
}

/**
 * A literature review: written section by section in the background, so while it runs this shows its progress and
 * the sections finished so far. ``compact`` is the card on the search page.
 */
export function ReviewView({ id, compact = false }: { id: string; compact?: boolean }) {
  const { data: review, isLoading, error } = useReview(id)
  const remove = useDeleteReview()
  const again = useStartReview()
  const navigate = useNavigate()
  const [copied, setCopied] = useState(false)

  if (isLoading) return <Spinner label="Loading the review…" />
  if (error || !review) return <Notice tone="error" title="This review could not be loaded">It may have been deleted.</Notice>

  const writing = isWriting(review)
  const { step = 0, of = 1, label } = review.progress
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(review.markdown ?? '')
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard unavailable: the export still works.
    }
  }
  const restart = () =>
    again.mutate(review.mode === 'map' && review.topic ? { topic_slug: review.topic.slug } : { query: review.query ?? '' },
      { onSuccess: (r) => navigate(`/reviews/${r.id}`) })

  return (
    <article className={cn('relative grid gap-5 rounded-xl border border-line bg-surface', compact ? 'p-4' : 'p-5 sm:p-6')}>
      <span className="ai-ring" data-active={writing} aria-hidden="true" />
      <header className="flex flex-wrap items-start gap-3">
        <Oracle mode={writing ? 'thinking' : 'done'} size={compact ? 44 : 52} />
        <div className="grid min-w-0 flex-1 gap-1.5">
          <h2 className={cn('font-semibold leading-snug text-fg', compact ? 'text-[15px]' : 'text-[19px]')}>
            {compact ? <Link to={`/reviews/${review.id}`} className="hover:underline">{review.title}</Link> : review.title}
          </h2>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-3">
            <ReviewSourceChip review={review} />
            {review.status === 'done' && <span>{review.cited} papers cited · {timeAgo(review.finished_at ?? review.created_at ?? '')}</span>}
            {review.status === 'done' && review.output_tokens > 0 && <span className="font-mono">{(review.input_tokens + review.output_tokens).toLocaleString()} tokens</span>}
          </div>
        </div>
        {review.status === 'done' && (
          <div className="flex items-center gap-1.5">
            <AddToProjectMenu membershipRef={`review:${review.id}`} item={{ kind: 'review', id: review.id }} compact />
            <Button variant="ghost" size="sm" onClick={copy}>{copied ? <><Check /> Copied</> : <><Copy /> Copy</>}</Button>
            <DownloadMenu options={[
              { label: 'Markdown', hint: 'The review with its references', path: `/reviews/${review.id}/export`, params: { format: 'md' }, filename: `${fileName(review.title)}.md` },
              { label: 'BibTeX', hint: 'The papers it cites', path: `/reviews/${review.id}/export`, params: { format: 'bib' }, filename: `${fileName(review.title)}.bib` },
            ]} />
          </div>
        )}
      </header>

      {writing && (
        <div className="grid gap-1.5" aria-live="polite">
          <div className="flex items-center justify-between text-[12.5px] text-fg-2">
            <span className="font-myth text-[14px]">{label ?? 'Starting'}…</span>
            <span className="font-mono text-fg-3 tabular-nums">{Math.min(step, of)} / {of}</span>
          </div>
          <span className="h-1 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
            <span className="block h-full rounded-full bg-accent transition-[width]" style={{ width: `${Math.round((Math.min(step, of) / Math.max(of, 1)) * 100)}%` }} />
          </span>
          <p className="text-[12px] text-fg-3">
            {review.mode === 'map' ? 'Reading the map’s papers and writing one section at a time; usually a few minutes.' : 'Writing from the search results’ abstracts; about a minute.'}
            {' '}You can leave this page: it is saved in Library → Reviews.
          </p>
        </div>
      )}

      {review.status === 'failed' && (
        <Notice tone="error" title="The review was not finished">
          {review.error ?? 'Something went wrong.'}
          <div className="mt-2"><Button size="sm" variant="secondary" disabled={again.isPending} onClick={restart}><RotateCcw /> Write it again</Button></div>
          {again.error && <p className="mt-1 text-[12px] text-bad">{apiErrorMessage(again.error, 'Could not start it')}</p>}
        </Notice>
      )}

      {(!compact || review.status === 'done') && review.sections.some((s) => s.markdown) && (
        <div className={cn('grid gap-4', compact && 'max-h-[520px] overflow-y-auto pr-1')}>
          {review.sections.map((s) => (
            <section key={s.key} className="grid gap-2">
              {s.level <= 2 ? <h3 className="text-[16px] font-semibold text-fg">{s.title}</h3> : <h4 className="text-[14px] font-semibold text-fg">{s.title}</h4>}
              {s.markdown ? <Markdown text={s.markdown} /> : writing && s.key !== 'history' ? <p className="text-[13px] text-fg-3">Not written yet.</p> : null}
            </section>
          ))}
          {review.status === 'done' && review.sources.length > 0 && (
            <section className="grid gap-2">
              <h3 className="text-[16px] font-semibold text-fg">References</h3>
              <ol className="grid gap-1.5">{review.sources.map((src) => <Reference key={src.n} source={src} />)}</ol>
            </section>
          )}
        </div>
      )}

      {review.status === 'done' && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-line pt-3 text-[11.5px] text-fg-3">
          <Sparkles className="h-3 w-3 text-accent" aria-hidden="true" />
          Written by AI{review.model ? ` (${review.model})` : ''}. Every [n] points at a real paper; check the claims against them.
          {!compact && (
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => remove.mutate(review.id, { onSuccess: () => navigate('/library/reviews') })}>
              <Trash2 /> Delete
            </Button>
          )}
        </footer>
      )}
    </article>
  )
}
