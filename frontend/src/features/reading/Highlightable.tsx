import { useEffect, useRef, useState, type ElementType, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Highlighter, MessageSquarePlus } from 'lucide-react'
import type { Highlight, NewHighlight } from '../../api/queries/personal'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'

const CONTEXT = 32

/** Where a highlight sits in ``text`` now: its stored place if the quote is still there, else the first match. */
function locate(text: string, h: Highlight): { start: number; end: number } | null {
  const a = h.anchor
  if (a && text.slice(a.start, a.end) === h.quote) return a
  const at = text.indexOf(h.quote)
  return at >= 0 ? { start: at, end: at + h.quote.length } : null
}

interface Pending {
  quote: string
  start: number
  top: number
  left: number
}

/**
 * Text you can highlight: select some, then save it (with a comment if you like). Your highlights in this field are
 * marked in place. Without ``onHighlight`` it is plain text.
 */
export function Highlightable({ text, field, highlights = [], onHighlight, as: Tag = 'p', className, context }: {
  text: string
  field: string
  highlights?: Highlight[]
  onHighlight?: (h: NewHighlight) => Promise<unknown> | void
  as?: ElementType
  className?: string
  context?: NewHighlight['context']
}) {
  const ref = useRef<HTMLElement>(null)
  const [pending, setPending] = useState<Pending | null>(null)

  const capture = () => {
    const sel = window.getSelection()
    const root = ref.current
    if (!onHighlight || !root || !sel || sel.isCollapsed || !sel.rangeCount) return setPending(null)
    const range = sel.getRangeAt(0)
    if (!root.contains(range.commonAncestorContainer)) return setPending(null)
    const before = document.createRange()
    before.selectNodeContents(root)
    before.setEnd(range.startContainer, range.startOffset)
    const raw = range.toString()
    const quote = raw.trim()
    if (!quote) return setPending(null)
    const start = before.toString().length + (raw.length - raw.trimStart().length)
    const rect = range.getBoundingClientRect()
    setPending({ quote, start, top: rect.top, left: rect.left + rect.width / 2 })
  }

  const save = async (comment?: string) => {
    if (!pending || !onHighlight) return
    const { quote, start } = pending
    setPending(null)
    window.getSelection()?.removeAllRanges()
    await onHighlight({
      field, quote, start, comment: comment || null, context,
      prefix: text.slice(Math.max(0, start - CONTEXT), start),
      suffix: text.slice(start + quote.length, start + quote.length + CONTEXT),
    })
  }

  return (
    <>
      <Tag ref={ref} className={className} onMouseUp={capture} onKeyUp={capture}>
        {marked(text, highlights.filter((h) => h.field === field))}
      </Tag>
      {pending && <SelectionMenu pending={pending} onSave={save} onClose={() => setPending(null)} />}
    </>
  )
}

/** ``text`` with the highlights that can still be found wrapped in <mark>; overlapping ones keep the first. */
function marked(text: string, highlights: Highlight[]): ReactNode {
  const spans = highlights
    .map((h) => ({ h, at: locate(text, h) }))
    .filter((x): x is { h: Highlight; at: { start: number; end: number } } => x.at !== null)
    .sort((a, b) => a.at.start - b.at.start)
  if (!spans.length) return text
  const out: ReactNode[] = []
  let cursor = 0
  for (const { h, at } of spans) {
    if (at.start < cursor) continue
    if (at.start > cursor) out.push(text.slice(cursor, at.start))
    out.push(
      <mark key={h.id} title={h.comment ?? 'Your highlight'} className="rounded-[3px] bg-accent-soft px-px text-fg">
        {text.slice(at.start, at.end)}
      </mark>,
    )
    cursor = at.end
  }
  if (cursor < text.length) out.push(text.slice(cursor))
  return out
}

function SelectionMenu({ pending, onSave, onClose }: { pending: Pending; onSave: (comment?: string) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [commenting, setCommenting] = useState(false)
  const [comment, setComment] = useState('')

  useEffect(() => {
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    // A scroll moves the text away from the menu; the selection can be made again.
    window.addEventListener('scroll', onClose, true)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('scroll', onClose, true)
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  const width = commenting ? 280 : 210
  const left = Math.max(8, Math.min(pending.left - width / 2, window.innerWidth - width - 8))
  const top = pending.top > 56 ? pending.top - (commenting ? 52 : 42) : pending.top + 24
  return createPortal(
    <div ref={ref} role="dialog" aria-label="Highlight the selection"
      className="fixed z-[80] flex items-center gap-1 rounded-lg border border-line bg-surface p-1 shadow-pop" style={{ top, left, width }}>
      {commenting ? (
        <form className="flex w-full gap-1" onSubmit={(e) => { e.preventDefault(); onSave(comment.trim()) }}>
          <input autoFocus value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Your comment" aria-label="Comment"
            className={cn(inputClass, 'h-7 flex-1 text-[12.5px]')} />
          <Button type="submit" variant="primary" size="sm">Save</Button>
        </form>
      ) : (
        <>
          <Button variant="ghost" size="sm" onClick={() => onSave()}><Highlighter /> Highlight</Button>
          <Button variant="ghost" size="sm" onClick={() => setCommenting(true)}><MessageSquarePlus /> Comment</Button>
        </>
      )}
    </div>,
    document.body,
  )
}
