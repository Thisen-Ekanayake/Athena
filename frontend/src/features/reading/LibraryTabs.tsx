import { useState } from 'react'
import { Link } from 'react-router-dom'
import { BookCheck, GitBranch, NotebookPen, Search } from 'lucide-react'
import { useLibraryNotes, useReadHistory, type AboutPaper, type MeKind } from '../../api/queries/personal'
import { CATEGORY_LABELS, timeAgo } from '../../components/items/format'
import { usePanelStore } from '../../store/panelStore'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { EmptyState } from '../../ui/EmptyState'
import { Segmented } from '../../ui/Segmented'
import { SkeletonRows } from '../../ui/Skeleton'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { HighlightList } from './NotesSection'

/** A paper's title that opens it where it lives: the side panel for a feed item, its map for a map paper. */
function PaperTitle({ about, className }: { about: AboutPaper; className?: string }) {
  const open = usePanelStore((s) => s.open)
  const cls = cn('text-left font-medium text-fg hover:underline', className)
  if (about.kind === 'item') return <button type="button" onClick={() => open(about.id)} className={cls}>{about.title}</button>
  if (about.map) return <Link to={`/evolution/${about.map.slug}?paper=${about.id}`} className={cls}>{about.title}</Link>
  return <span className={cn(cls, 'hover:no-underline')}>{about.title}</span>
}

function Meta({ about, when }: { about: AboutPaper; when?: string | null }) {
  const bits = about.kind === 'item'
    ? [about.source, about.category && CATEGORY_LABELS[about.category]]
    : [about.year ? String(about.year) : null]
  return (
    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-fg-3">
      {about.kind === 'paper' && about.map && <Chip><GitBranch aria-hidden="true" />{about.map.name}</Chip>}
      {bits.filter(Boolean).join(' · ')}
      {when && <span>· {timeAgo(when)}</span>}
    </p>
  )
}

/** Your notes and highlights, one entry per paper, the most recently touched first. */
export function NotesTab() {
  const [kind, setKind] = useState<'all' | MeKind>('all')
  const [q, setQ] = useState('')
  const { data, isLoading } = useLibraryNotes(kind, q.trim())

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented label="Papers from" value={kind} onChange={setKind}
          options={[{ value: 'all', label: 'All' }, { value: 'item', label: 'Feed' }, { value: 'paper', label: 'Maps' }]} />
        <label className="relative ml-auto flex min-w-[220px] items-center">
          <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-fg-3" aria-hidden="true" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your notes" aria-label="Search your notes"
            className={cn(inputClass, 'w-full pl-8')} />
        </label>
      </div>
      {isLoading ? <SkeletonRows count={3} /> : !data?.length ? (
        <EmptyState icon={NotebookPen} title={q ? 'Nothing matches' : 'No notes yet'}>
          {q ? 'Try other words.' : 'Open a paper, write in "Your notes", or select text in its summary or abstract to highlight it.'}
        </EmptyState>
      ) : (
        <ul className="grid gap-3">
          {data.map((e) => (
            <li key={`${e.about.kind}:${e.about.id}`} className="grid gap-3 rounded-xl border border-line bg-surface p-4">
              <div>
                <PaperTitle about={e.about} className="text-[14px]" />
                <Meta about={e.about} when={e.updated_at} />
              </div>
              {e.note && <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-fg">{e.note.body}</p>}
              {e.highlights.length > 0 && <HighlightList highlights={e.highlights} compact />}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** What you marked read, in the feed and in maps, the latest first. */
export function ReadTab() {
  const { data, isLoading, fetchNextPage, hasNextPage, isFetchingNextPage } = useReadHistory()
  const entries = data?.pages.flatMap((p) => p.entries) ?? []
  const total = data?.pages[0]?.pagination.total ?? 0

  if (isLoading) return <SkeletonRows count={4} />
  if (!entries.length) {
    return <EmptyState icon={BookCheck} title="Nothing read yet">Mark a paper read from its row, its panel, or a map's reading path.</EmptyState>
  }
  return (
    <div className="grid gap-3">
      <p className="text-[12.5px] text-fg-3">{total.toLocaleString()} {total === 1 ? 'paper' : 'papers'} read</p>
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {entries.map((e) => (
          <li key={`${e.about.kind}:${e.about.id}`} className="px-4 py-3">
            <PaperTitle about={e.about} className="text-[13.5px]" />
            <Meta about={e.about} when={e.read_at} />
          </li>
        ))}
      </ul>
      {hasNextPage && (
        <Button variant="secondary" className="justify-self-center" disabled={isFetchingNextPage} onClick={() => fetchNextPage()}>
          {isFetchingNextPage ? <Spinner className="h-3.5 w-3.5" /> : null} Show more
        </Button>
      )}
    </div>
  )
}
