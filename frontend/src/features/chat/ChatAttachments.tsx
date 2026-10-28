import { FileText, GitBranch, Image as ImageIcon, RotateCcw, Sparkles, X } from 'lucide-react'
import { useDetachChatFile, useDetachChatMap, useShareChatMap, type Chat, type MapPick } from '../../api/queries/chats'
import { cn } from '../../ui/cn'

const chip = 'inline-flex max-w-[240px] items-center gap-1.5 rounded-lg border border-line bg-surface-2 py-1 pr-1 pl-2 text-[12px] text-fg-2'
const iconButton = 'rounded p-0.5 text-fg-3 hover:bg-surface-3 hover:text-fg'

/**
 * What the chat holds for every turn: its maps (open one beside the chat, switch its summary for the model, remove
 * it) and its files (take one out of the turns; it stays on its message and can come back).
 */
export function ChatAttachments({ chat, onOpenMap }: { chat: Chat; onOpenMap: (slug: string) => void }) {
  const share = useShareChatMap(chat.id)
  const removeMap = useDetachChatMap(chat.id)
  const detach = useDetachChatFile(chat.id)
  const files = (chat.files ?? []).filter((f) => f.status === 'ready')
  const maps = chat.maps ?? []
  if (!maps.length && !files.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="In this chat">
      {maps.map((m) => (
        <li key={m.topic_id} className={cn(chip, m.share && 'border-accent-line')}>
          <button type="button" onClick={() => onOpenMap(m.slug)} className="flex min-w-0 items-center gap-1.5 hover:text-fg" title={`Open ${m.name} beside the chat`}>
            <GitBranch className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
            <span className="truncate">{m.name}</span>
            <span className="font-mono text-[10.5px] text-fg-3">{m.key}</span>
          </button>
          <button type="button" aria-pressed={m.share} disabled={share.isPending}
            onClick={() => share.mutate({ topic: m.slug, share: !m.share })}
            aria-label={m.share ? `Stop giving ${m.name} to the model` : `Give ${m.name} to the model`}
            title={m.share ? 'The model gets a summary of this map (as a graph). Click to stop.' : 'Only you see this map. Click to give the model a summary.'}
            className={cn(iconButton, m.share && 'text-accent')}>
            <Sparkles className="h-3 w-3" />
          </button>
          <button type="button" onClick={() => removeMap.mutate(m.slug)} aria-label={`Remove ${m.name}`} title="Remove from the chat" className={iconButton}>
            <X className="h-3 w-3" />
          </button>
        </li>
      ))}
      {files.map((f) => (
        <li key={f.id} className={cn(chip, f.detached && 'border-dashed text-fg-3')}
          title={f.detached ? 'Taken out of the chat: the model no longer reads it' : 'The model reads this file on every turn'}>
          {f.kind === 'image' ? <ImageIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
          <span className={cn('truncate', f.detached && 'line-through')}>{f.filename}</span>
          {f.detached ? (
            <button type="button" onClick={() => detach.mutate({ fileId: f.id, detached: false })} aria-label={`Bring back ${f.filename}`} title="Bring it back into the chat" className={iconButton}>
              <RotateCcw className="h-3 w-3" />
            </button>
          ) : (
            <button type="button" onClick={() => detach.mutate({ fileId: f.id, detached: true })} aria-label={`Take ${f.filename} out of the chat`} title="Take it out of the chat (it stays on its message)" className={iconButton}>
              <X className="h-3 w-3" />
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Maps picked for a chat that does not exist yet; they are attached when its first message goes. */
export function StagedMaps({ maps, names, onChange }: {
  maps: MapPick[]
  names: Record<string, string>
  onChange: (maps: MapPick[]) => void
}) {
  if (!maps.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Maps to attach">
      {maps.map((m) => (
        <li key={m.id} className={cn(chip, m.share && 'border-accent-line')}>
          <GitBranch className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
          <span className="truncate">{names[m.id] ?? m.id}</span>
          <button type="button" aria-pressed={m.share} onClick={() => onChange(maps.map((x) => (x.id === m.id ? { ...x, share: !x.share } : x)))}
            aria-label={m.share ? 'Stop giving it to the model' : 'Give it to the model'}
            title={m.share ? 'The model gets a summary of this map. Click to stop.' : 'Only you see this map. Click to give the model a summary.'}
            className={cn(iconButton, m.share && 'text-accent')}>
            <Sparkles className="h-3 w-3" />
          </button>
          <button type="button" onClick={() => onChange(maps.filter((x) => x.id !== m.id))} aria-label={`Remove ${names[m.id] ?? m.id}`} className={iconButton}>
            <X className="h-3 w-3" />
          </button>
        </li>
      ))}
    </ul>
  )
}
