import { useRef, useState } from 'react'
import { Archive, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from 'lucide-react'
import { useDeleteChat, useUpdateChat, type ChatSummary } from '../../api/queries/chats'
import { Popover } from '../../ui/Popover'
import { cn } from '../../ui/cn'

const menuItem = 'flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-2'
const iconButton = 'flex items-center justify-center rounded-md hover:bg-surface hover:text-fg'

/**
 * A chat row's ⋯ menu (rename, archive, delete) and its pin, as in the sidebar and a project's chat list.
 * Rename hands back to the row, which edits the title in place (`RenameField`).
 */
export function ChatActions({ chat, onRename, onDeleted, size = 'sm', align = 'start' }: {
  chat: ChatSummary
  onRename: () => void
  onDeleted?: () => void
  size?: 'sm' | 'md'
  /** Which edge of the ⋯ button the menu lines up with */
  align?: 'start' | 'end'
}) {
  const update = useUpdateChat()
  const remove = useDeleteChat()
  const box = size === 'sm' ? 'h-6 w-6' : 'h-7 w-7'
  return (
    <>
      <Popover
        label="Chat actions"
        width={180}
        estHeight={120}
        align={align}
        trigger={({ ref, open, toggle }) => (
          <button ref={ref} type="button" onClick={toggle} aria-expanded={open} aria-label={`Actions for ${chat.title}`} title="More" className={cn(iconButton, box, 'text-fg-3')}>
            <MoreHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        )}
      >
        {(close) => (
          <div className="grid py-1 text-[13px]">
            <button type="button" className={menuItem} onClick={() => {
              close()
              onRename()
            }}><Pencil className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" />Rename</button>
            <button type="button" className={menuItem} onClick={() => {
              close()
              update.mutate({ id: chat.id, archived: true })
            }}><Archive className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" />Archive</button>
            <button type="button" className={cn(menuItem, 'text-bad')} onClick={() => {
              close()
              if (window.confirm(`Delete “${chat.title}”? Its artifacts stay.`)) remove.mutate(chat.id, { onSuccess: onDeleted })
            }}><Trash2 className="h-3.5 w-3.5" aria-hidden="true" />Delete</button>
          </div>
        )}
      </Popover>
      <button
        type="button"
        onClick={() => update.mutate({ id: chat.id, pinned: !chat.pinned })}
        aria-pressed={chat.pinned}
        aria-label={chat.pinned ? `Unpin ${chat.title}` : `Pin ${chat.title}`}
        title={chat.pinned ? 'Unpin' : 'Pin'}
        className={cn(iconButton, box, chat.pinned ? 'text-accent' : 'text-fg-3')}
      >
        {chat.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden="true" /> : <Pin className="h-3.5 w-3.5" aria-hidden="true" />}
      </button>
    </>
  )
}

/** A chat's title in place: Enter or leaving the field saves, Escape keeps the old one. */
export function RenameField({ chat, onDone, className }: { chat: ChatSummary; onDone: () => void; className?: string }) {
  const update = useUpdateChat()
  const [value, setValue] = useState(chat.title)
  const finished = useRef(false)
  const finish = (save: boolean) => {
    if (finished.current) return
    finished.current = true
    const title = value.trim()
    if (save && title && title !== chat.title) update.mutate({ id: chat.id, title })
    onDone()
  }
  return (
    <input
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onFocus={(e) => e.target.select()}
      onBlur={() => finish(true)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          finish(true)
        } else if (e.key === 'Escape') {
          finish(false)
        }
      }}
      autoFocus
      maxLength={120}
      aria-label="Chat title"
      className={cn('w-full rounded-md border border-line-strong bg-surface px-2 text-fg outline-none', className)}
    />
  )
}

/** Classes that show a row's actions while it is hovered, focused, or its menu is open (put `group` on the row). */
export const SHOW_ON_HOVER = 'hidden group-hover:flex group-focus-within:flex group-has-[[aria-expanded=true]]:flex'
/** The opposite, for what the actions replace (a pinned mark, a date). */
export const HIDE_ON_HOVER = 'group-hover:hidden group-focus-within:hidden group-has-[[aria-expanded=true]]:hidden'
