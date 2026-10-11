import { useState, type FormEvent } from 'react'
import { Bookmark, Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useCreateList, useDeleteList, useListItems, useLists, useRenameList } from '../api/queries/saved'
import { apiErrorMessage } from '../api/error'
import { ItemList } from '../components/items/ItemRow'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { SkeletonRows } from '../ui/Skeleton'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'

const inputClass = 'h-8 min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-2.5 text-[13px] text-fg placeholder:text-fg-3 focus:border-accent-line focus:outline-none'

/** Reading lists you make yourself, such as "Computer vision" or "To read this week". */
export function SavedPage() {
  const { data: lists, isLoading } = useLists()
  const createList = useCreateList()
  const deleteList = useDeleteList()
  const renameList = useRenameList()
  const [pickedId, setPickedId] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  // The user's pick if it still exists, else the first list.
  const selectedId = (pickedId && lists?.some((l) => l.id === pickedId) ? pickedId : lists?.[0]?.id) ?? null
  const selected = lists?.find((l) => l.id === selectedId)
  const { data: items, isLoading: itemsLoading } = useListItems(selectedId)

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
    <div className="mx-auto max-w-[1100px]">
      <PageHeader title="Saved" description="Your own reading lists. Save any item from its bookmark button." />
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
                    <span className="font-mono text-[11.5px] text-fg-3">{list.item_count}</span>
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
          {!isLoading && !lists?.length ? (
            <EmptyState icon={Bookmark} title="No lists yet">Name a list on the left, then save items into it from their bookmark button.</EmptyState>
          ) : itemsLoading ? (
            <SkeletonRows count={4} />
          ) : items?.length ? (
            <ItemList items={items} />
          ) : selected ? (
            <EmptyState icon={Bookmark} title={`${selected.name} is empty`}>Open any item and use its bookmark button to save it here.</EmptyState>
          ) : null}
        </section>
      </div>
    </div>
  )
}
