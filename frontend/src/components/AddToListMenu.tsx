import { useState, useRef, useEffect } from 'react'
import { MoreHorizontal, Check, Plus, FolderPlus, Loader2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useLists, useAddToList, useRemoveFromList, useCreateList } from '../api/queries/saved'
import { apiErrorMessage } from '../api/error'

interface AddToListMenuProps {
  itemId: string
}

export function AddToListMenu({ itemId }: AddToListMenuProps) {
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  const { data: lists, isLoading } = useLists(itemId, open)
  const addToList = useAddToList()
  const removeFromList = useRemoveFromList()
  const createList = useCreateList()

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setCreating(false)
        setNewName('')
        setError(null)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  const toggleMembership = (listId: string, contains: boolean) => {
    if (contains) removeFromList.mutate({ listId, itemId })
    else addToList.mutate({ listId, itemId })
  }

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) return
    setError(null)
    try {
      const list = await createList.mutateAsync(name)
      await addToList.mutateAsync({ listId: list.id, itemId })
      setNewName('')
      setCreating(false)
    } catch (e: unknown) {
      setError(apiErrorMessage(e, 'Could not create list.'))
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Add to list"
        aria-label="Add to list"
        className={`p-1.5 rounded-md transition-colors hover:bg-white/5 ${
          open ? 'text-accent-primary' : 'text-text-muted hover:text-text-primary'
        }`}
      >
        <MoreHorizontal className="w-4 h-4" />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 mt-2 w-60 rounded-xl border border-white/10 shadow-2xl z-50 overflow-hidden"
            style={{ background: 'var(--color-void)' }}
          >
            <div className="px-3 py-2.5 border-b border-white/5">
              <p className="text-[10px] font-display font-bold text-text-ghost uppercase tracking-[0.15em]">Add to list</p>
            </div>

            <div className="max-h-56 overflow-y-auto custom-scrollbar py-1">
              {isLoading ? (
                <div className="flex justify-center py-4">
                  <Loader2 className="w-4 h-4 text-text-ghost animate-spin" />
                </div>
              ) : lists && lists.length > 0 ? (
                lists.map(list => {
                  const contains = !!list.contains_item
                  return (
                    <button
                      key={list.id}
                      onClick={() => toggleMembership(list.id, contains)}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-white/5 transition-colors group/item"
                    >
                      <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors ${
                        contains ? 'bg-accent-primary border-accent-primary' : 'border-white/20 group-hover/item:border-white/40'
                      }`}>
                        {contains && <Check className="w-3 h-3 text-white" />}
                      </span>
                      <span className="flex-1 min-w-0 truncate text-[13px] font-medium text-text-secondary group-hover/item:text-text-primary">
                        {list.name}
                      </span>
                      <span className="text-[10px] font-mono text-text-ghost shrink-0">{list.item_count}</span>
                    </button>
                  )
                })
              ) : (
                <p className="px-3 py-3 text-[12px] text-text-muted">No lists yet — create one below.</p>
              )}
            </div>

            <div className="border-t border-white/5 p-2">
              {creating ? (
                <div className="space-y-2">
                  <div className="flex gap-2">
                    <input
                      autoFocus
                      value={newName}
                      onChange={e => setNewName(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') handleCreate(); if (e.key === 'Escape') { setCreating(false); setNewName('') } }}
                      placeholder="e.g. NLP, Computer Vision"
                      className="flex-1 min-w-0 glass-base border border-white/10 text-white rounded-lg px-2.5 py-1.5 text-[12px] focus:outline-none focus:border-accent-primary transition-all placeholder:text-text-ghost"
                    />
                    <button
                      onClick={handleCreate}
                      disabled={!newName.trim() || createList.isPending}
                      className="px-2.5 py-1.5 rounded-lg bg-accent-primary text-white text-[11px] font-bold hover:shadow-glow-primary transition-all disabled:opacity-40 shrink-0"
                    >
                      {createList.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  {error && <p className="text-[11px] text-[#E05A6B] px-0.5">{error}</p>}
                </div>
              ) : (
                <button
                  onClick={() => { setCreating(true); setError(null) }}
                  className="w-full flex items-center gap-2.5 px-2 py-2 rounded-lg text-left text-[13px] font-medium text-accent-primary hover:bg-accent-primary/10 transition-colors"
                >
                  <FolderPlus className="w-4 h-4" />
                  Create new list
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
