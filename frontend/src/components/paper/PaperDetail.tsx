import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, EyeOff, Layers, Sparkles } from 'lucide-react'
import type { FeedItem } from '../../api/client'
import { useItemDetail } from '../../api/queries'
import { useAddHighlight, useMe, useReaction } from '../../api/queries/personal'
import { useRelatedItems } from '../../api/queries/related'
import { usePanelStore } from '../../store/panelStore'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { Highlightable } from '../../features/reading/Highlightable'
import { NotesSection } from '../../features/reading/NotesSection'
import { CATEGORY_LABELS, timeAgo } from '../items/format'
import { ReactionButtons, ReadToggle } from '../items/ItemActions'
import { ScoreBadge } from '../items/ScoreBadge'
import { CitationMomentum } from '../../features/momentum/CitationMomentum'
import { AskPaper } from './AskPaper'
import { PlaceInEvolution } from './PlaceInEvolution'
import { ScoreBreakdown } from './ScoreBreakdown'

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('grid gap-2.5', className)}>
      <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-fg-3">{title}</h3>
      {children}
    </section>
  )
}

/** Everything about one item: summary, score, questions and related reading. Shared by the side panel and the full page. */
export function PaperDetail({ itemId, initial, layout }: { itemId: string; initial?: FeedItem | null; layout: 'panel' | 'page' }) {
  const { data, isLoading, error } = useItemDetail(itemId, true)
  const me = useMe('item', itemId)
  const addHighlight = useAddHighlight('item', itemId)
  const react = useReaction()
  const item = data ?? initial ?? null
  const [showScore, setShowScore] = useState(false)
  const [showAbstract, setShowAbstract] = useState(false)

  if (!item) {
    return isLoading ? (
      <div className="p-5"><Spinner label="Loading…" /></div>
    ) : (
      <div className="p-5"><Notice tone="error" title="This item could not be loaded">{error ? 'Check that the API is running, then try again.' : 'It may have been removed.'}</Notice></div>
    )
  }

  const abstract = data?.abstract
  const highlights = me.data?.highlights ?? []
  const reaction = me.data ? me.data.reaction : item.me?.reaction
  const read = me.data ? me.data.read : !!item.me?.read
  const mark = (h: Parameters<typeof addHighlight.mutateAsync>[0]) => addHighlight.mutateAsync(h)

  return (
    <div className={cn('grid gap-6', layout === 'panel' ? 'p-5' : 'py-2')}>
      <header className="grid gap-2.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-fg-3">
          <span className="text-fg-2">{item.source.name}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={item.published_at}>{timeAgo(item.published_at)}</time>
          {CATEGORY_LABELS[item.category] && <Chip>{CATEGORY_LABELS[item.category]}</Chip>}
        </div>
        <h2 className={cn('font-semibold leading-snug tracking-[-0.01em] text-fg', layout === 'panel' ? 'text-[18px]' : 'text-[24px]')}>
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{item.title}</a>
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <ScoreBadge score={item.score} />
          <button type="button" onClick={() => setShowScore((v) => !v)} aria-expanded={showScore} className="inline-flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg">
            Why this score <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showScore && 'rotate-180')} />
          </button>
          {item.cluster && (
            <Link to={`/clusters/${item.cluster.id}`} className="ml-auto inline-flex items-center gap-1.5 text-[12.5px] text-fg-3 hover:text-fg">
              <Layers className="h-3.5 w-3.5" aria-hidden="true" /> {item.cluster.label}
            </Link>
          )}
        </div>
        {showScore && <div className="rounded-lg border border-line bg-surface-2/50 p-3"><ScoreBreakdown itemId={item.id} /></div>}
        <div className="flex flex-wrap items-center gap-1">
          <ReadToggle itemId={item.id} read={read} withLabel />
          <span className="mx-1 h-4 w-px bg-line" aria-hidden="true" />
          <ReactionButtons itemId={item.id} reaction={reaction} />
          {reaction === 'hide' ? (
            <span className="ml-1 flex items-center gap-1 text-[12.5px] text-fg-3">
              Hidden from your feed
              <Button variant="ghost" size="sm" onClick={() => react.mutate({ id: item.id, reaction: null })}>Undo</Button>
            </span>
          ) : (
            <Button variant="ghost" size="sm" title="Leave it out of your feed, and show less like it"
              onClick={() => react.mutate({ id: item.id, reaction: 'hide' })}>
              <EyeOff /> Not interested
            </Button>
          )}
        </div>
      </header>

      <Section title="Summary">
        {item.summary ? (
          <div className="grid gap-3">
            <Highlightable text={item.summary} field="summary" highlights={highlights} onHighlight={mark}
              className="text-[14px] leading-relaxed text-fg-2" />
            {item.takeaways && item.takeaways.length > 0 && (
              <ul className="grid gap-1.5">
                {item.takeaways.map((t, i) => (
                  <li key={i} className="flex gap-2 text-[13.5px] leading-relaxed text-fg-2">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden="true" />
                    <Highlightable as="span" text={t} field={`takeaway:${i}`} highlights={highlights} onHighlight={mark} />
                  </li>
                ))}
              </ul>
            )}
            <p className="flex items-center gap-1.5 text-[11.5px] text-fg-3"><Sparkles className="h-3 w-3 text-accent" aria-hidden="true" /> Written by AI from the item's text</p>
          </div>
        ) : (
          <p className="text-[13px] text-fg-3">{item.summary_status === 'pending' ? 'The summary is being written.' : 'No summary yet.'}</p>
        )}
        {abstract && (
          <div>
            <button type="button" onClick={() => setShowAbstract((v) => !v)} aria-expanded={showAbstract} className="inline-flex items-center gap-1 text-[12.5px] text-fg-3 hover:text-fg">
              {showAbstract ? 'Hide the abstract' : 'Read the abstract'} <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showAbstract && 'rotate-180')} />
            </button>
            {showAbstract && (
              <Highlightable text={abstract} field="abstract" highlights={highlights} onHighlight={mark}
                className="mt-2 text-[13.5px] leading-relaxed text-fg-2" />
            )}
          </div>
        )}
      </Section>

      {item.category === 'paper' && (
        <Section title="Citations">
          <CitationMomentum itemId={item.id} title={item.title} />
        </Section>
      )}

      <Section title="Your notes">
        {me.data ? <NotesSection key={item.id} kind="item" id={item.id} me={me.data} /> : <Spinner />}
      </Section>

      <PlaceInEvolution itemId={item.id} />

      <AskPaper itemId={item.id} />

      <Related itemId={item.id} />
    </div>
  )
}

function Related({ itemId }: { itemId: string }) {
  const { data, isLoading } = useRelatedItems(itemId)
  const open = usePanelStore((s) => s.open)
  if (isLoading) return <Section title="Related"><Spinner /></Section>
  if (!data?.length) return null
  return (
    <Section title="Related">
      <ul className="grid gap-px overflow-hidden rounded-lg border border-line bg-line">
        {data.map((r) => (
          <li key={r.id}>
            <button type="button" onClick={() => open(r.id)} className="flex w-full items-start gap-3 bg-surface px-3 py-2.5 text-left hover:bg-surface-2">
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-medium leading-snug text-fg">{r.title}</span>
                <span className="mt-0.5 block text-[12px] text-fg-3">
                  {[CATEGORY_LABELS[r.category], timeAgo(r.published_at)].filter(Boolean).join(' · ')}
                </span>
              </span>
              <span className="mt-0.5 shrink-0 font-mono text-[12px] text-fg-3 tabular-nums" title="How similar it is to this item">
                {Math.round(r.similarity * 100)}% similar
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Section>
  )
}
