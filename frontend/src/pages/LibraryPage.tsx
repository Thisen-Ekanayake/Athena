import { useState, type FormEvent } from 'react'
import { NavLink, useParams } from 'react-router-dom'
import { Bookmark, Check, EyeOff, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useCreateList, useDeleteList, useListItems, useLists, useRenameList } from '../api/queries/saved'
import { apiErrorMessage } from '../api/error'
import { ItemList } from '../components/items/ItemRow'
import { NotesTab, ReadTab } from '../features/reading/LibraryTabs'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { SkeletonRows } from '../ui/Skeleton'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'

const inputClass = 'h-8 min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-2.5 text-[13px] text-fg placeholder:text-fg-3 focus:border-accent-line focus:outline-none'

const TABS = [
  { id: 'lists', label: 'Lists' },
  { id: 'notes', label: 'Notes and highlights' },
  { id: 'read', label: 'Read' },
] as const
type Tab = (typeof TABS)[number]['id']

/** Your own reading: lists you made, your notes and highlights on papers, and what you have read. */
export function LibraryPage() {
  const { tab } = useParams<{ tab?: string }>()
  const active: Tab = TABS.some((t) => t.id === tab) ? (tab as Tab) : 'lists'
  return (
    <div className="mx-auto max-w-[1100px]">
      <PageHeader title="Library" description="Your reading lists, your notes and highlights, and what you have read. Only you see them." />
      <nav className="mb-5 flex gap-1 border-b border-line" aria-label="Library sections">
        {TABS.map((t) => (
          <NavLink key={t.id} to={t.id === 'lists' ? '/library' : `/library/${t.id}`} end
            className={cn('-mb-px border-b-2 px-3 pb-2 text-[13.5px] transition-colors',
              active === t.id ? 'border-accent text-fg' : 'border-transparent text-fg-2 hover:text-fg')}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      {active === 'lists' && <ListsTab />}
      {active === 'notes' && <NotesTab />}
      {active === 'read' && <ReadTab />}
    </div>
  )
}

/** Reading lists you make yourself, such as "Computer vision" or "To read this week". */
function ListsTab() {
  const { data: lists, isLoading } = useLists()
  const createList = useCreateList()
  const deleteList = useDeleteList()
  const renameList = useRenameList()
  const [pickedId, setPickedId] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [hideRead, setHideRead] = useState(false)

  // The user's pick if it still exists, else the first list.
  const selectedId = (pickedId && lists?.some((l) => l.id === pickedId) ? pickedId : lists?.[0]?.id) ?? null
  const selected = lists?.find((l) => l.id === selectedId)
  const { data: items, isLoading: itemsLoading } = useListItems(selectedId, hideRead)

  const create = async (e: FormEvent) => {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    try {
      const list = await createList.mutateAsync(name)
      setPickedId(list.id)
      setNewName('')
    } catch {
      // Shown below from createList.error.
    }
  }

  const rename = async (e: FormEvent, id: string) => {
    e.preventDefault()
    const name = editName.trim()
    if (!name) return
    try {
      await renameList.mutateAsync({ id, name })
      setEditingId(null)
    } catch {
      // Shown below from renameList.error.
    }
  }

  return (
    <div>
      <div className="grid gap-6 md:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="grid content-start gap-1">
          {isLoading ? (
            <Spinner label="Loading lists…" />
          ) : (
            lists?.map((list) =>
              editingId === list.id ? (
                <form key={list.id} onSubmit={(e) => rename(e, list.id)} className="flex gap-1">
                  <input id={`rename-${list.id}`} autoFocus value={editName} onChange={(e) => setEditName(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && setEditingId(null)} aria-label="List name" className={inputClass} />
                  <Button type="submit" variant="ghost" size="icon" aria-label="Save name"><Check /></Button>
                  <Button variant="ghost" size="icon" onClick={() => setEditingId(null)} aria-label="Cancel"><X /></Button>
                </form>
              ) : (
                <div key={list.id} className={cn('group flex h-8 items-center rounded-lg pr-1 transition-colors', list.id === selectedId ? 'bg-surface-2 shadow-[0_0_0_1px_var(--line)]' : 'hover:bg-surface-2/60')}>
                  <button type="button" onClick={() => setPickedId(list.id)} className="flex h-full min-w-0 flex-1 items-center gap-2 px-2.5 text-left text-[13.5px]">
                    <span className={cn('min-w-0 flex-1 truncate', list.id === selectedId ? 'text-fg' : 'text-fg-2')}>{list.name}</span>
                    <span className="font-mono text-[11.5px] text-fg-3" title={`${list.read_count ?? 0} of ${list.item_count} read`}>
                      {list.item_count ? `${list.read_count ?? 0}/${list.item_count}` : 0}
                    </span>
                  </button>
                  <span className="flex opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                    <Button variant="ghost" size="icon-sm" title="Rename" aria-label={`Rename ${list.name}`} onClick={() => { setEditingId(list.id); setEditName(list.name) }}><Pencil /></Button>
                    <Button variant="ghost" size="icon-sm" title="Delete" aria-label={`Delete ${list.name}`} onClick={() => setConfirmDelete(list.id)}><Trash2 /></Button>
                  </span>
                </div>
              ),
            )
          )}
          <form onSubmit={create} className="mt-2 flex gap-1">
            <input id="new-list-name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New list" aria-label="New list name" className={inputClass} />
            <Button type="submit" variant="secondary" size="icon" disabled={!newName.trim() || createList.isPending} aria-label="Create list"><Plus /></Button>
          </form>
          {createList.isError && <p className="text-[12px] text-bad">{apiErrorMessage(createList.error, 'The list could not be created.')}</p>}
          {renameList.isError && <p className="text-[12px] text-bad">{apiErrorMessage(renameList.error, 'The list could not be renamed.')}</p>}
        </aside>

        <section className="min-w-0">
          {confirmDelete && (
            <Notice tone="warn" className="mb-4" title={`Delete "${lists?.find((l) => l.id === confirmDelete)?.name}"?`}>
              <p>The items stay in your library; only the list goes.</p>
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="primary" onClick={() => { deleteList.mutate(confirmDelete); setConfirmDelete(null) }}>Delete list</Button>
                <Button size="sm" variant="secondary" onClick={() => setConfirmDelete(null)}>Keep it</Button>
              </div>
            </Notice>
          )}
          {selected && selected.item_count > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <div className="flex min-w-[160px] flex-1 items-center gap-2 text-[12.5px] text-fg-3">
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
                  <span className="block h-full rounded-full bg-good" style={{ width: `${Math.round(((selected.read_count ?? 0) / selected.item_count) * 100)}%` }} />
                </span>
                {selected.read_count ?? 0} of {selected.item_count} read
              </div>
              <Button variant="ghost" size="sm" aria-pressed={hideRead} onClick={() => setHideRead((v) => !v)} className={cn(hideRead && 'bg-surface-2 text-fg')}>
                <EyeOff /> Hide read
              </Button>
            </div>
          )}
          {!isLoading && !lists?.length ? (
            <EmptyState icon={Bookmark} title="No lists yet">Name a list on the left, then save items into it from their bookmark button.</EmptyState>
          ) : itemsLoading ? (
            <SkeletonRows count={4} />
          ) : items?.length ? (
            <ItemList items={items} collapseHidden={false} />
          ) : selected && hideRead && selected.item_count > 0 ? (
            <EmptyState icon={Check} title="All read">Everything in {selected.name} is marked read.</EmptyState>
          ) : selected ? (
            <EmptyState icon={Bookmark} title={`${selected.name} is empty`}>Open any item and use its bookmark button to save it here.</EmptyState>
          ) : null}
        </section>
      </div>
    </div>
  )
}
