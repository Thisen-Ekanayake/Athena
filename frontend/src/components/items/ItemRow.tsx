import { ExternalLink, Flame, GitBranch } from 'lucide-react'
import type { FeedItem } from '../../api/client'
import { usePanelStore } from '../../store/panelStore'
import { buttonClass } from '../../ui/buttonClass'
import { Chip } from '../../ui/Chip'
import { cn } from '../../ui/cn'
import { CATEGORY_LABELS, timeAgo } from './format'
import { SaveMenu } from './SaveMenu'
import { ScoreBadge } from './ScoreBadge'

/** One feed item as a list row. Clicking it opens the paper side panel. */
export function ItemRow({ item, showSummary = true }: { item: FeedItem; showSummary?: boolean }) {
  const open = usePanelStore((s) => s.open)
  const isOpen = usePanelStore((s) => s.itemId === item.id)

  return (
    <article className={cn('group relative flex gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2/60', isOpen && 'bg-surface-2')}>
      <div className="min-w-0 flex-1">
        <h3 className="text-[14px] font-medium leading-snug text-fg">
          {/* The title button stretches over the whole row; the action buttons sit above it. */}
          <button type="button" onClick={() => open(item)} className="text-left after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:rounded-lg focus-visible:after:outline-2 focus-visible:after:outline-accent">
            {item.title}
          </button>
        </h3>
        {showSummary && item.summary && <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-fg-2">{item.summary}</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-fg-3">
          <span className="text-fg-2">{item.source.name}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={item.published_at}>{timeAgo(item.published_at)}</time>
          {CATEGORY_LABELS[item.category] && <Chip>{CATEGORY_LABELS[item.category]}</Chip>}
          {item.is_trending && <Chip tone="accent"><Flame aria-hidden="true" />Trending</Chip>}
          {!!item.milestones_cited && (
            <span title="Cites milestones of your evolution maps; open it to see which">
              <Chip><GitBranch aria-hidden="true" />Cites {item.milestones_cited} {item.milestones_cited === 1 ? 'milestone' : 'milestones'}</Chip>
            </span>
          )}
        </div>
      </div>
      <div className="relative z-10 flex shrink-0 items-start gap-0.5">
        <div className="flex gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 max-md:opacity-100">
          <SaveMenu itemId={item.id} />
          <a href={item.url} target="_blank" rel="noopener noreferrer" title="Open the original" aria-label="Open the original" className={buttonClass('ghost', 'icon-sm')}>
            <ExternalLink />
          </a>
        </div>
        <ScoreBadge score={item.score} className="mt-[3px] ml-1" />
      </div>
    </article>
  )
}

/** Rows separated by hairlines, in their own bordered box unless `bare` (e.g. inside a card). */
export function ItemList({ items, showSummary, bare = false }: { items: FeedItem[]; showSummary?: boolean; bare?: boolean }) {
  return (
    <div className={cn('divide-y divide-line', !bare && 'overflow-hidden rounded-xl border border-line bg-surface')}>
      {items.map((item) => <ItemRow key={item.id} item={item} showSummary={showSummary} />)}
    </div>
  )
}
