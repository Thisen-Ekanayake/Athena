import { useRef, useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { useDeleteHighlight, useSaveNote, useUpdateHighlight, type Highlight, type Me, type MeKind } from '../../api/queries/personal'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'

const SAVE_AFTER_MS = 800

const SECTION: Record<string, string> = {
  abstract: 'Abstract', intro: 'Introduction', related_work: 'Related work', method: 'Method', results: 'Results',
  discussion: 'Discussion', limitations: 'Limitations', conclusion: 'Conclusion', future_work: 'Future work', other: 'Body',
}

/** Where a highlight came from, in words: "Abstract", "Takeaway 2", "Passage · Method". */
function fieldLabel(h: Highlight): string {
  if (h.field.startsWith('takeaway:')) return `Takeaway ${Number(h.field.slice(9)) + 1}`
  if (h.field === 'passage') {
    const section = h.context?.section ? SECTION[String(h.context.section)] ?? String(h.context.section) : null
    return section ? `Passage · ${section}` : 'Passage'
  }
  return h.field === 'summary' ? 'Summary' : h.field === 'abstract' ? 'Abstract' : h.field
}

/** Your note on a paper (saved as you type) and your highlights in it. Only you see them. */
export function NotesSection({ kind, id, me }: { kind: MeKind; id: string; me: Me }) {
  const save = useSaveNote(kind, id)
  const [draft, setDraft] = useState(me.note?.body ?? '')
  const [dirty, setDirty] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flush = (body: string) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    save.mutate(body, { onSuccess: () => setDirty(false) })
  }
  const change = (body: string) => {
    setDraft(body)
    setDirty(true)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => flush(body), SAVE_AFTER_MS)
  }

  return (
    <div className="grid gap-3">
      <div className="grid gap-1">
        <textarea
          value={draft}
          onChange={(e) => change(e.target.value)}
          onBlur={() => dirty && flush(draft)}
          placeholder="Your notes: what it does, how it relates to your work, what to check…"
          aria-label="Your notes"
          rows={3}
          className="min-h-[76px] resize-y rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13.5px] leading-relaxed text-fg [field-sizing:content] placeholder:text-fg-3 focus:border-accent-line focus:outline-none"
        />
        <p className="text-[11.5px] text-fg-3" aria-live="polite">
          {save.isError ? <span className="text-bad">{apiErrorMessage(save.error, 'Not saved')}</span>
            : save.isPending || dirty ? 'Saving…' : me.note || draft ? 'Saved · only you see your notes' : 'Select text above to highlight it'}
        </p>
      </div>
      {me.highlights.length > 0 && <HighlightList highlights={me.highlights} />}
    </div>
  )
}

export function HighlightList({ highlights, compact = false }: { highlights: Highlight[]; compact?: boolean }) {
  return (
    <ul className="grid gap-2">
      {highlights.map((h) => <HighlightEntry key={h.id} h={h} compact={compact} />)}
    </ul>
  )
}

function HighlightEntry({ h, compact }: { h: Highlight; compact: boolean }) {
  const update = useUpdateHighlight()
  const remove = useDeleteHighlight()
  const [editing, setEditing] = useState(false)
  const [comment, setComment] = useState(h.comment ?? '')
  const detached = h.anchor === null && h.field !== 'passage'

  return (
    <li className="group grid gap-1">
      <div className="flex items-start gap-2">
        <blockquote className={cn('min-w-0 flex-1 border-l-2 border-accent pl-2.5 text-fg-2', compact ? 'text-[12.5px]' : 'text-[13px]')}>
          “{h.quote}”
        </blockquote>
        <span className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 max-md:opacity-100">
          <Button variant="ghost" size="icon-sm" title="Comment" aria-label="Edit the comment" onClick={() => setEditing(true)}><Pencil /></Button>
          <Button variant="ghost" size="icon-sm" title="Remove" aria-label="Remove the highlight" onClick={() => remove.mutate(h.id)}><Trash2 /></Button>
        </span>
      </div>
      {editing ? (
        <form className="flex gap-1 pl-3" onSubmit={(e) => { e.preventDefault(); update.mutate({ id: h.id, comment: comment.trim() || null }, { onSuccess: () => setEditing(false) }) }}>
          <input autoFocus value={comment} onChange={(e) => setComment(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && setEditing(false)}
            placeholder="Your comment" aria-label="Comment" className={cn(inputClass, 'h-7 flex-1 text-[12.5px]')} />
          <Button type="submit" variant="secondary" size="sm">Save</Button>
        </form>
      ) : h.comment ? (
        <p className="pl-3 text-[12.5px] text-fg">{h.comment}</p>
      ) : null}
      <p className="pl-3 text-[11.5px] text-fg-3">
        {fieldLabel(h)}{detached && ' · no longer in the text'}
      </p>
    </li>
  )
}
