import { Flame, GitBranch, Heart, NotebookPen, ThumbsDown, ThumbsUp, TrendingUp } from 'lucide-react'
import type { FeedItem } from '../../api/client'
import { usePanelStore } from '../../store/panelStore'
import { Chip } from '../../ui/Chip'
import { cn } from '../../ui/cn'
import { CATEGORY_LABELS, timeAgo } from './format'
import { HiddenRow, MoreMenu, ReactionButtons, ReadToggle } from './ItemActions'
import { SaveMenu } from './SaveMenu'
import { ScoreBadge } from './ScoreBadge'

/** A For-you item this close to what the user liked gets a quiet hint (unless they reacted to it themselves). */
const MATCH = 0.9

/**
 * One feed item as a list row. Clicking it opens the paper side panel. ``collapseHidden``: an item marked "not
 * interested" shrinks to a line with Undo (lists that keep hidden items, like saved lists, turn it off).
 */
export function ItemRow({ item, showSummary = true, collapseHidden = true }: { item: FeedItem; showSummary?: boolean; collapseHidden?: boolean }) {
  const open = usePanelStore((s) => s.open)
  const isOpen = usePanelStore((s) => s.itemId === item.id)
  const me = item.me
  const read = !!me?.read

  if (collapseHidden && me?.reaction === 'hide') return <HiddenRow itemId={item.id} title={item.title} />

  return (
    <article className={cn('group relative flex gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2/60 max-md:flex-wrap max-md:gap-y-1', isOpen && 'bg-surface-2')}>
      <div className="min-w-0 flex-1">
        <h3 className={cn('text-[14px] font-medium leading-snug', read ? 'text-fg-2' : 'text-fg')}>
          {/* The title button stretches over the whole row; the action buttons sit above it. */}
          <button type="button" onClick={() => open(item)} className="text-left after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:rounded-lg focus-visible:after:outline-2 focus-visible:after:outline-accent">
            {item.title}
            {read && <span className="sr-only"> (read)</span>}
          </button>
        </h3>
        {showSummary && item.summary && <p className={cn('mt-1 line-clamp-2 text-[13px] leading-relaxed', read ? 'text-fg-3' : 'text-fg-2')}>{item.summary}</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-fg-3">
          <span className="text-fg-2">{item.source.name}</span>
          <span aria-hidden="true">·</span>
          <time dateTime={item.published_at}>{timeAgo(item.published_at)}</time>
          {CATEGORY_LABELS[item.category] && <Chip>{CATEGORY_LABELS[item.category]}</Chip>}
          {item.is_trending && <Chip tone="accent"><Flame aria-hidden="true" />Trending</Chip>}
          {item.match === 'exact' && <span title="Its title names what you searched for"><Chip tone="accent">Exact match</Chip></span>}
          {!!item.milestones_cited && (
            <span title="Cites milestones of your evolution maps; open it to see which">
              <Chip><GitBranch aria-hidden="true" />Cites {item.milestones_cited} {item.milestones_cited === 1 ? 'milestone' : 'milestones'}</Chip>
            </span>
          )}
          {!!item.citation_gain_7d && item.citation_gain_7d > 0 && (
            <span title="Citations gained in the last 7 days (Semantic Scholar)">
              <Chip><TrendingUp aria-hidden="true" />+{item.citation_gain_7d} {item.citation_gain_7d === 1 ? 'cite' : 'cites'} this week</Chip>
            </span>
          )}
          {me?.reaction === 'up' && <span title="You liked this"><ThumbsUp className="h-3.5 w-3.5 text-accent" aria-label="You liked this" /></span>}
          {me?.reaction === 'down' && <span title="You asked for less like this"><ThumbsDown className="h-3.5 w-3.5" aria-label="You asked for less like this" /></span>}
          {!me?.reaction && item.interest != null && item.interest >= MATCH && (
            <span title="Close to what you liked and saved"><Heart className="h-3.5 w-3.5 text-accent" aria-label="Close to what you liked and saved" /></span>
          )}
          {me?.annotated && <span title="You wrote notes or highlights on this"><NotebookPen className="h-3.5 w-3.5" aria-label="Has your notes" /></span>}
        </div>
      </div>
      {/* Narrow screens have no hover: the actions are always shown, on their own line under the item. */}
      <div className="relative z-10 flex shrink-0 items-start gap-0.5 max-md:w-full max-md:justify-end">
        <div className="flex gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 max-md:opacity-100">
          <ReadToggle itemId={item.id} read={read} />
          <ReactionButtons itemId={item.id} reaction={me?.reaction} />
          <SaveMenu itemId={item.id} />
          <MoreMenu item={item} />
        </div>
        <ScoreBadge score={item.score} className="mt-[3px] ml-1" />
      </div>
    </article>
  )
}

/** Rows separated by hairlines, in their own bordered box unless `bare` (e.g. inside a card). */
export function ItemList({ items, showSummary, bare = false, collapseHidden = true }: {
  items: FeedItem[]; showSummary?: boolean; bare?: boolean; collapseHidden?: boolean
}) {
  return (
    <div className={cn('divide-y divide-line', !bare && 'overflow-hidden rounded-xl border border-line bg-surface')}>
      {items.map((item) => <ItemRow key={item.id} item={item} showSummary={showSummary} collapseHidden={collapseHidden} />)}
    </div>
  )
}
