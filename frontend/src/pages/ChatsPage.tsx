import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive, ArchiveRestore, FolderKanban, MessageSquare, Pin, Plus, Search, Trash2 } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { useChats, useDeleteChat, useUpdateChat } from '../api/queries/chats'
import { Button, ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { PageHeader } from '../ui/PageHeader'
import { Segmented } from '../ui/Segmented'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'
import { inputClass } from '../ui/inputClass'

type View = 'chats' | 'archived'

/** Every chat, alone or in a project, pinned first then most recent, with a search over their titles; or the archived ones. */
export function ChatsPage() {
  const [q, setQ] = useState('')
  const [view, setView] = useState<View>('chats')
  const query = useDeferredValue(q.trim())
  const archived = view === 'archived'
  const chats = useChats({ q: query, limit: 200, archived })
  const update = useUpdateChat()
  const remove = useDeleteChat()

  return (
    <div className="mx-auto grid max-w-3xl">
      <PageHeader
        title="Chats"
        description="Conversations with your local models, alone or inside a project."
        actions={<ButtonLink to="/chats/new" variant="primary"><Plus /> New chat</ButtonLink>}
      />
      <div className="mb-4 flex items-center gap-2">
        <label className="relative block flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-fg-3" aria-hidden="true" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={archived ? 'Search archived chats' : 'Search your chats'} aria-label="Search chats" className={cn(inputClass, 'h-9 w-full pl-8')} />
        </label>
        <Segmented<View>
          label="Which chats"
          value={view}
          onChange={setView}
          options={[{ value: 'chats', label: 'Chats' }, { value: 'archived', label: <><Archive aria-hidden="true" />Archived</> }]}
        />
      </div>
      {chats.isLoading ? <Spinner label="Loading chats…" /> : chats.data?.length ? (
        <ul className="grid divide-y divide-line rounded-xl border border-line bg-surface">
          {chats.data.map((c) => (
            <li key={c.id} className="flex items-center hover:bg-surface-2">
              <Link to={`/chats/${c.id}`} className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3">
                <MessageSquare className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-[13.5px] text-fg">
                    <span className="truncate">{c.title}</span>
                    {c.pinned && <Pin className="h-3 w-3 shrink-0 text-fg-3" aria-label="Pinned" />}
                  </span>
                  <span className="flex items-center gap-2 text-[12px] text-fg-3">
                    {c.project_name && <span className="inline-flex items-center gap-1"><FolderKanban className="h-3 w-3" aria-hidden="true" />{c.project_name}</span>}
                    <span>{formatDistanceToNow(new Date(c.updated_at), { addSuffix: true })}</span>
                  </span>
                </span>
              </Link>
              {archived && (
                <span className="flex shrink-0 gap-1 pr-3">
                  <Button variant="ghost" size="sm" onClick={() => update.mutate({ id: c.id, archived: false })}><ArchiveRestore /> Unarchive</Button>
                  <Button variant="ghost" size="icon-sm" aria-label={`Delete ${c.title}`} title="Delete" onClick={() => {
                    if (window.confirm(`Delete “${c.title}”? Its artifacts stay.`)) remove.mutate(c.id)
                  }}><Trash2 /></Button>
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        archived ? (
          <EmptyState icon={Archive} title={query ? 'No archived chats match' : 'No archived chats'}>
            {!query && 'Archive a chat from its menu to take it out of your lists without deleting it.'}
          </EmptyState>
        ) : (
          <EmptyState icon={MessageSquare} title={query ? 'No chats match' : 'No chats yet'} action={!query && <ButtonLink to="/chats/new" variant="secondary"><Plus /> Start one</ButtonLink>}>
            {!query && 'Ask your local models anything; they can search papers, ask your maps and write artifacts.'}
          </EmptyState>
        )
      )}
    </div>
  )
}
