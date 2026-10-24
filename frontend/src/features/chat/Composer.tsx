import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, FileText, Image as ImageIcon, Paperclip, Square, X } from 'lucide-react'
import { useChatModels, type Effort } from '../../api/queries/chats'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'
import { ModelPicker } from './ModelPicker'

const ACCEPT = '.pdf,.txt,.md,.markdown,.csv,.tsv,.json,.tex,.bib,.py,.rst,.yaml,.yml,.png,.jpg,.jpeg,.webp,.gif,application/pdf,text/*,image/*'
const PREF_KEY = 'athena-chat-model'

/** The last model and effort picked, for new chats. */
function lastChoice(): { model?: string; effort?: Effort } {
  try {
    return JSON.parse(localStorage.getItem(PREF_KEY) ?? '{}')
  } catch {
    return {}
  }
}

function remember(choice: { model: string; effort: Effort }) {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify(choice))
  } catch {
    // private mode: the choice only lasts for this chat
  }
}

export interface Outgoing {
  text: string
  files: File[]
  model: string
  effort: Effort
}

/** Where messages are written: the text, attached files, the model and effort, and send or stop. */
export function Composer({ onSend, onStop, streaming, initial, placeholder = 'Ask anything…', autoFocus, className }: {
  onSend: (m: Outgoing) => void | Promise<void>
  onStop?: () => void
  streaming?: boolean
  /** The chat's own model and effort, which win over the last ones picked */
  initial?: { model?: string | null; effort?: Effort | null }
  placeholder?: string
  autoFocus?: boolean
  className?: string
}) {
  const models = useChatModels()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [picked, setPicked] = useState<{ model?: string; effort?: Effort }>({})
  const fileRef = useRef<HTMLInputElement>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)

  const saved = lastChoice()
  const available = models.data?.models.map((m) => m.id) ?? []
  const fallbackModel = [initial?.model, saved.model].find((m) => m && (available.length === 0 || available.includes(m))) ?? models.data?.default ?? ''
  const model = picked.model ?? fallbackModel
  const thinks = models.data?.models.find((m) => m.id === model)?.reasoning ?? false
  const effort: Effort = thinks ? (picked.effort ?? initial?.effort ?? saved.effort ?? models.data?.default_effort ?? 'low') : 'off'

  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 280)}px`
  }, [text])

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (streaming || !text.trim() || !model) return
    void onSend({ text: text.trim(), files, model, effort })
    setText('')
    setFiles([])
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  const addFiles = (list: FileList | null) => {
    if (list?.length) setFiles((f) => [...f, ...Array.from(list)])
  }

  return (
    <form
      onSubmit={submit}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault()
        addFiles(e.dataTransfer.files)
      }}
      className={cn('relative grid gap-2 rounded-2xl border border-line bg-surface p-2.5 shadow-[0_1px_0_rgba(0,0,0,0.2)] focus-within:border-line-strong', className)}
    >
      <span className="ai-ring" data-active={!!streaming} aria-hidden="true" />
      {files.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Attached files">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="inline-flex max-w-[220px] items-center gap-1.5 rounded-lg border border-line bg-surface-2 py-1 pr-1 pl-2 text-[12px] text-fg-2">
              {f.type.startsWith('image/') ? <ImageIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
              <span className="truncate">{f.name}</span>
              <button type="button" onClick={() => setFiles((all) => all.filter((_, k) => k !== i))} aria-label={`Remove ${f.name}`} className="rounded p-0.5 text-fg-3 hover:bg-surface-3 hover:text-fg">
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <textarea
        ref={areaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onPaste={(e) => addFiles(e.clipboardData.files)}
        placeholder={placeholder}
        aria-label="Message"
        rows={1}
        autoFocus={autoFocus}
        className="max-h-[280px] min-h-[44px] w-full resize-none bg-transparent px-1.5 py-1 text-[14px] leading-relaxed text-fg placeholder:text-fg-3 focus:outline-none"
      />
      <div className="flex items-center gap-1">
        <input ref={fileRef} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => {
          addFiles(e.target.files)
          e.target.value = ''
        }} />
        <Button variant="ghost" size="icon-sm" onClick={() => fileRef.current?.click()} aria-label="Attach files" title="Attach PDFs, text files or images">
          <Paperclip />
        </Button>
        <ModelPicker
          models={models.data}
          model={model}
          effort={effort}
          onChange={(next) => {
            setPicked(next)
            remember(next)
          }}
        />
        <span className="ml-auto" />
        {streaming ? (
          <Button variant="secondary" size="icon-sm" onClick={onStop} aria-label="Stop" title="Stop">
            <Square className="fill-current" />
          </Button>
        ) : (
          <Button type="submit" variant="primary" size="icon-sm" disabled={!text.trim() || !model} aria-label="Send" title="Send (Enter)">
            <ArrowUp />
          </Button>
        )}
      </div>
    </form>
  )
}
