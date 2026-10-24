import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router-dom'
import { FolderKanban, MessageSquare, Plus, Search } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { useChats } from '../api/queries/chats'
import { ButtonLink } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { PageHeader } from '../ui/PageHeader'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'
import { inputClass } from '../ui/inputClass'

/** Every chat, alone or in a project, most recent first, with a search over their titles. */
export function ChatsPage() {
  const [q, setQ] = useState('')
  const query = useDeferredValue(q.trim())
  const chats = useChats({ q: query, limit: 200 })

  return (
    <div className="mx-auto grid max-w-3xl">
      <PageHeader
        title="Chats"
        description="Conversations with your local models, alone or inside a project."
        actions={<ButtonLink to="/chats/new" variant="primary"><Plus /> New chat</ButtonLink>}
      />
      <label className="relative mb-4 block">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-fg-3" aria-hidden="true" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your chats" aria-label="Search chats" className={cn(inputClass, 'h-9 w-full pl-8')} />
      </label>
      {chats.isLoading ? <Spinner label="Loading chats…" /> : chats.data?.length ? (
        <ul className="grid divide-y divide-line rounded-xl border border-line bg-surface">
          {chats.data.map((c) => (
            <li key={c.id}>
              <Link to={`/chats/${c.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-2">
                <MessageSquare className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] text-fg">{c.title}</span>
                  <span className="flex items-center gap-2 text-[12px] text-fg-3">
                    {c.project_name && <span className="inline-flex items-center gap-1"><FolderKanban className="h-3 w-3" aria-hidden="true" />{c.project_name}</span>}
                    <span>{formatDistanceToNow(new Date(c.updated_at), { addSuffix: true })}</span>
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState icon={MessageSquare} title={query ? 'No chats match' : 'No chats yet'} action={!query && <ButtonLink to="/chats/new" variant="secondary"><Plus /> Start one</ButtonLink>}>
          {!query && 'Ask your local models anything; they can search papers, ask your maps and write artifacts.'}
        </EmptyState>
      )}
    </div>
  )
}
