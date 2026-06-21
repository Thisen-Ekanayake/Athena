import { useState } from 'react'
import { Bookmark, Plus, Trash2, Pencil, Check, X, Orbit, Loader2, FolderPlus } from 'lucide-react'
import { motion } from 'framer-motion'
import {
  useLists, useCreateList, useDeleteList, useRenameList, useListItems,
} from '../api/queries/saved'
import { apiErrorMessage } from '../api/error'
import { FeedCard } from '../components/FeedCard'
import { CardSkeleton } from '../components/CardSkeleton'
import { Alert } from '../components/shared/Alert'

export function SavedPage() {
  const { data: lists, isLoading: listsLoading } = useLists()
  const createList = useCreateList()
  const deleteList = useDeleteList()
  const renameList = useRenameList()

  const [pickedId, setPickedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')

  // Derive the active list: the user's pick if still valid, else the first list.
  // (Derived rather than synced via an effect, to avoid cascading renders.)
  const selectedId =
    (pickedId && lists?.some(l => l.id === pickedId) ? pickedId : lists?.[0]?.id) ?? null
  const setSelectedId = setPickedId

  const { data: items, isLoading: itemsLoading } = useListItems(selectedId)
  const selectedList = lists?.find(l => l.id === selectedId)

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) return
    try {
      const list = await createList.mutateAsync(name)
      setSelectedId(list.id)
      setNewName('')
      setCreating(false)
    } catch { /* surfaced via createList.isError below */ }
  }

  const handleRename = async (id: string) => {
    const name = editName.trim()
    if (!name) return
    try {
      await renameList.mutateAsync({ id, name })
      setEditingId(null)
    } catch { /* surfaced via renameList.isError below */ }
  }

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      <div className="glass-base border-b border-white/5 pt-28 pb-10 px-8">
        <div className="max-w-[1200px] mx-auto flex items-center gap-3">
          <Bookmark className="w-6 h-6 text-accent-primary" />
          <div>
            <h1 className="text-3xl font-display font-bold text-white tracking-tight">Saved <span className="text-accent-primary">Lists</span></h1>
            <p className="text-sm text-text-muted mt-1 font-medium">Curate intelligence into collections like NLP or Computer Vision.</p>
          </div>
        </div>
      </div>

      <div className="max-w-[1200px] mx-auto w-full px-6 py-10 md:px-12 grid md:grid-cols-4 gap-10">
        {/* Lists rail */}
        <aside className="md:col-span-1 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-[10px] font-display font-bold text-text-ghost uppercase tracking-[0.2em]">Collections</span>
            <span className="text-[10px] font-mono text-text-ghost">{lists?.length ?? 0}</span>
          </div>

          {listsLoading ? (
            <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 text-text-ghost animate-spin" /></div>
          ) : (
            <nav className="space-y-1">
              {lists?.map(list => (
                <div key={list.id} className="group/list relative">
                  {editingId === list.id ? (
                    <div className="flex items-center gap-1.5 px-2 py-1.5">
                      <input
                        autoFocus
                        value={editName}
                        onChange={e => setEditName(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleRename(list.id); if (e.key === 'Escape') setEditingId(null) }}
                        className="flex-1 min-w-0 glass-void border border-white/10 text-white rounded-lg px-2 py-1 text-[13px] focus:outline-none focus:border-accent-primary"
                      />
                      <button onClick={() => handleRename(list.id)} className="p-1 text-[#5AE07F] hover:bg-[#5AE07F]/10 rounded"><Check className="w-3.5 h-3.5" /></button>
                      <button onClick={() => setEditingId(null)} className="p-1 text-text-ghost hover:text-white rounded"><X className="w-3.5 h-3.5" /></button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setSelectedId(list.id)}
                      className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left transition-all ${
                        selectedId === list.id
                          ? 'bg-accent-primary/10 text-accent-primary border border-accent-primary/20'
                          : 'text-text-muted hover:text-text-primary hover:bg-white/5 border border-transparent'
                      }`}
                    >
                      <span className="flex-1 min-w-0 truncate text-[13px] font-display font-bold">{list.name}</span>
                      <span className="text-[10px] font-mono text-text-ghost shrink-0">{list.item_count}</span>
                      <span className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover/list:opacity-100 transition-opacity">
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => { e.stopPropagation(); setEditingId(list.id); setEditName(list.name) }}
                          className="p-0.5 text-text-ghost hover:text-accent-primary"
                          title="Rename"
                        >
                          <Pencil className="w-3 h-3" />
                        </span>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => { e.stopPropagation(); if (confirm(`Delete list "${list.name}"? Saved items are not deleted.`)) deleteList.mutate(list.id) }}
                          className="p-0.5 text-text-ghost hover:text-[#E05A6B]"
                          title="Delete list"
                        >
                          <Trash2 className="w-3 h-3" />
                        </span>
                      </span>
                    </button>
                  )}
                </div>
              ))}

              {/* Create new list */}
              {creating ? (
                <div className="flex gap-1.5 px-1 pt-1">
                  <input
                    autoFocus
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleCreate(); if (e.key === 'Escape') { setCreating(false); setNewName('') } }}
                    placeholder="e.g. NLP"
                    className="flex-1 min-w-0 glass-void border border-white/10 text-white rounded-lg px-2.5 py-2 text-[13px] focus:outline-none focus:border-accent-primary placeholder:text-text-ghost"
                  />
                  <button
                    onClick={handleCreate}
                    disabled={!newName.trim() || createList.isPending}
                    className="px-2.5 rounded-lg bg-accent-primary text-white hover:shadow-glow-primary transition-all disabled:opacity-40 shrink-0"
                  >
                    {createList.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setCreating(true)}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-left text-[13px] font-display font-bold text-accent-primary hover:bg-accent-primary/10 transition-colors"
                >
                  <FolderPlus className="w-4 h-4" /> New list
                </button>
              )}
            </nav>
          )}

          {createList.isError && (
            <Alert type="error" title="Couldn't create">{apiErrorMessage(createList.error, 'Failed to create list.')}</Alert>
          )}
          {renameList.isError && (
            <Alert type="error" title="Couldn't rename">{apiErrorMessage(renameList.error, 'Failed to rename list.')}</Alert>
          )}
        </aside>

        {/* Items pane */}
        <section className="md:col-span-3 min-w-0">
          {!listsLoading && (!lists || lists.length === 0) ? (
            <div className="flex flex-col items-center justify-center py-32 text-center opacity-50">
              <div className="w-20 h-20 rounded-full glass-void border border-white/5 flex items-center justify-center mb-6">
                <Bookmark className="w-9 h-9 text-text-ghost" />
              </div>
              <h3 className="text-xl font-display font-medium text-white mb-2">No lists yet</h3>
              <p className="max-w-xs text-sm text-text-muted">Create a list, then use the ⋯ menu on any card to save items into it.</p>
            </div>
          ) : (
            <>
              {selectedList && (
                <div className="flex items-baseline gap-3 mb-6 px-1">
                  <h2 className="text-xl font-display font-bold text-white">{selectedList.name}</h2>
                  <span className="text-[11px] font-mono text-text-ghost uppercase tracking-wider">{selectedList.item_count} item{selectedList.item_count === 1 ? '' : 's'}</span>
                </div>
              )}

              {itemsLoading ? (
                <div className="grid gap-6">{[1, 2, 3].map(i => <CardSkeleton key={i} />)}</div>
              ) : items && items.length > 0 ? (
                <div className="grid gap-6">
                  {items.map((item, idx) => (
                    <motion.div key={item.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.04 }}>
                      <FeedCard item={item} index={idx} />
                    </motion.div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-28 text-center opacity-40">
                  <Orbit className="w-10 h-10 text-text-ghost animate-pulse mb-4" />
                  <h3 className="text-lg font-display font-medium text-white mb-1">This list is empty</h3>
                  <p className="max-w-xs text-sm text-text-muted">Open the ⋯ menu on any feed card and pick “{selectedList?.name}”.</p>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}
