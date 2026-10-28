import { useState, type ReactNode } from 'react'
import { GitBranch, NotebookPen, Plus } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { useAttachChatMaps, type Chat } from '../../api/queries/chats'
import { cn } from '../../ui/cn'
import { MapPicker } from './MapPicker'

/**
 * The right edge of a chat while no panel is open: its maps and artifacts, one click from opening beside the chat,
 * and a button to attach more maps. Names show on hover.
 */
export function SideRail({ chat, onOpenMap, onOpenArtifact }: {
  chat: Chat
  onOpenMap: (slug: string) => void
  onOpenArtifact: (id: string) => void
}) {
  const attach = useAttachChatMaps(chat.id)
  const [picking, setPicking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const maps = chat.maps ?? []
  return (
    <nav aria-label="Maps and artifacts" className="fixed top-1/2 right-3 z-30 hidden -translate-y-1/2 flex-col items-center gap-1 rounded-xl border border-line bg-surface p-1 shadow-pop sm:flex">
      {maps.map((m) => (
        <RailButton key={m.topic_id} label={`${m.name}${m.share ? ' · the model has a summary' : ''}`} onClick={() => onOpenMap(m.slug)}>
          <GitBranch className="h-4 w-4 text-accent" aria-hidden="true" />
          <span className={cn('absolute right-0.5 bottom-0.5 font-mono text-[9px] leading-none', m.share ? 'text-accent' : 'text-fg-3')}>{m.key}</span>
        </RailButton>
      ))}
      {chat.artifacts.length > 0 && maps.length > 0 && <span className="my-0.5 h-px w-5 bg-line" aria-hidden="true" />}
      {chat.artifacts.map((a) => (
        <RailButton key={a.id} label={a.title} onClick={() => onOpenArtifact(a.id)}>
          <NotebookPen className="h-4 w-4 text-fg-2" aria-hidden="true" />
        </RailButton>
      ))}
      {(maps.length > 0 || chat.artifacts.length > 0) && <span className="my-0.5 h-px w-5 bg-line" aria-hidden="true" />}
      <RailButton label="Attach a research map" onClick={() => {
        setError(null)
        setPicking(true)
      }}>
        <Plus className="h-4 w-4 text-fg-3" aria-hidden="true" />
        <GitBranch className="absolute right-0.5 bottom-0.5 h-2.5 w-2.5 text-fg-3" aria-hidden="true" />
      </RailButton>
      {picking && (
        <MapPicker onClose={() => setPicking(false)} attached={maps.map((m) => m.slug)} busy={attach.isPending} error={error}
          onAttach={(picks) => attach.mutate(picks, {
            onSuccess: () => {
              setPicking(false)
              if (picks.length === 1) onOpenMap(picks[0].id)
            },
            onError: (e) => setError(apiErrorMessage(e, 'The maps could not be attached.')),
          })} />
      )}
    </nav>
  )
}

function RailButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label}
      className="group relative flex h-9 w-9 items-center justify-center rounded-lg hover:bg-surface-2 focus-visible:bg-surface-2">
      {children}
      <span className="pointer-events-none absolute top-1/2 right-full mr-2 hidden max-w-[260px] -translate-y-1/2 truncate rounded-md border border-line bg-surface px-2 py-1 text-[12px] whitespace-nowrap text-fg shadow-pop group-hover:block group-focus-visible:block">
        {label}
      </span>
    </button>
  )
}
