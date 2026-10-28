import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { ArrowUp, FileText, GitBranch, Image as ImageIcon, Paperclip, Square, TriangleAlert, X } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { useChatModels, useModelState, warmModel, type Effort, type MapPick } from '../../api/queries/chats'
import { Button } from '../../ui/Button'
import { Popover } from '../../ui/Popover'
import { cn } from '../../ui/cn'
import { ContextMeter } from './ContextMeter'
import { LoadCard } from './LoadCard'
import { MapPicker } from './MapPicker'
import { ModelPicker, type ModelChoice } from './ModelPicker'

const FILE_ACCEPT = '.pdf,.txt,.md,.markdown,.csv,.tsv,.json,.tex,.bib,.py,.rst,.yaml,.yml,application/pdf,text/*'
const IMAGE_ACCEPT = '.png,.jpg,.jpeg,.webp,.gif,image/*'
const PREF_KEY = 'athena-chat-model'

/** The last model, effort and context picked, for new chats. */
function lastChoice(): { model?: string; effort?: Effort; context?: number | null } {
  try {
    return JSON.parse(localStorage.getItem(PREF_KEY) ?? '{}')
  } catch {
    return {}
  }
}

function remember(choice: ModelChoice) {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify(choice))
  } catch {
    // private mode: the choice only lasts for this chat
  }
}

const isImage = (f: File) => f.type.startsWith('image/') || /\.(png|jpe?g|webp|gif)$/i.test(f.name)

export interface Outgoing {
  text: string
  files: File[]
  model: string
  effort: Effort
  context: number | null
}

/** Where messages are written: the text, attached files and maps, the model, context and effort, and send or stop. */
export function Composer({ onSend, onStop, streaming, initial, placeholder = 'Ask anything…', autoFocus, className, contextUsed, onAttachMaps, attachedMaps, attached }: {
  onSend: (m: Outgoing) => void | Promise<void>
  onStop?: () => void
  streaming?: boolean
  /** The chat's own model, effort and context, which win over the last ones picked */
  initial?: { model?: string | null; effort?: Effort | null; context?: number | null }
  placeholder?: string
  autoFocus?: boolean
  className?: string
  /** How much of the context the conversation fills, for the ring before the send button */
  contextUsed?: { tokens: number; estimated: boolean } | null
  /** Attach research maps (the paperclip's menu offers them when given) */
  onAttachMaps?: (picks: MapPick[]) => void | Promise<void>
  /** Slugs of the maps already attached */
  attachedMaps?: string[]
  /** What the conversation already holds (its files and maps), above the text */
  attached?: ReactNode
}) {
  const models = useChatModels()
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [picked, setPicked] = useState<Partial<ModelChoice>>({})
  const [refused, setRefused] = useState<string | null>(null)
  const [watching, setWatching] = useState(false)
  const [picking, setPicking] = useState(false)
  const [mapError, setMapError] = useState<string | null>(null)
  const [attaching, setAttaching] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const imageRef = useRef<HTMLInputElement>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const warmed = useRef<string | null>(null)

  const saved = lastChoice()
  const list = models.data?.models ?? []
  const available = list.map((m) => m.id)
  const fallbackModel = [initial?.model, saved.model].find((m) => m && (available.length === 0 || available.includes(m))) ?? models.data?.default ?? ''
  const model = picked.model ?? fallbackModel
  const current = list.find((m) => m.id === model)
  const thinks = current?.reasoning ?? false
  const effort: Effort = thinks ? (picked.effort ?? initial?.effort ?? saved.effort ?? models.data?.default_effort ?? 'low') : 'off'
  const offered = current?.contexts?.map((c) => c.tokens) ?? []
  const context = offered.length
    ? [picked.context, initial?.context, saved.context].find((c): c is number => !!c && offered.includes(c)) ?? current?.default_context ?? offered[0]
    : null
  // Without the registry, images go to the router's vision preset whatever model is picked.
  const takesImages = models.data?.registry ? (current?.vision ?? false) : true
  const visionModel = list.find((m) => m.vision && m.id !== model)
  const strayImages = takesImages ? [] : files.filter(isImage)
  const loadedHere = current?.contexts?.find((c) => c.tokens === context)?.loaded ?? current?.loaded ?? false

  const state = useModelState(model, context, watching && !!models.data?.registry && !streaming)
  const showLoad = watching && !streaming && state.data && !['loaded', 'unknown'].includes(state.data.status)

  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 280)}px`
  }, [text])

  /** Load the model now, so it is ready by the time the message goes: on a pick, and when typing starts. */
  const warm = (m: string, ctx: number | null) => {
    if (!models.data?.registry || !m) return
    const key = `${m}@${ctx ?? ''}`
    if (warmed.current === key) return
    warmed.current = key
    setWatching(true)
    warmModel({ model: m, context: ctx }).catch(() => setWatching(false))
  }

  // Another context of the picked model is loaded (the last one a benchmark measured, or one picked elsewhere): load
  // the picked one, so the picker and the model server agree before the first message.
  const otherContextLoaded = !loadedHere && !streaming && !!current?.contexts?.some((c) => c.loaded)
  useEffect(() => {
    if (otherContextLoaded) warm(model, context)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [otherContextLoaded, model, context])

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (streaming || !text.trim() || !model || strayImages.length) return
    void onSend({ text: text.trim(), files, model, effort, context })
    setText('')
    setFiles([])
    setRefused(null)
    warmed.current = null
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  const addFiles = (incoming: FileList | null) => {
    if (!incoming?.length) return
    const all = Array.from(incoming)
    const images = all.filter(isImage)
    const kept = takesImages ? all : all.filter((f) => !isImage(f))
    setRefused(!takesImages && images.length ? `${model} reads text only, so ${images.length === 1 ? `${images[0].name} was` : `${images.length} images were`} not attached.` : null)
    if (kept.length) setFiles((f) => [...f, ...kept])
  }

  const attachMaps = async (picks: MapPick[]) => {
    if (!onAttachMaps) return
    setAttaching(true)
    setMapError(null)
    try {
      await onAttachMaps(picks)
      setPicking(false)
    } catch (e) {
      setMapError(apiErrorMessage(e, 'The maps could not be attached.'))
    } finally {
      setAttaching(false)
    }
  }

  const choose = (next: ModelChoice) => {
    setPicked(next)
    remember(next)
    setRefused(null)
    warm(next.model, next.context)
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
      {showLoad && state.data && <LoadCard state={state.data} />}
      {attached}
      {files.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Attached files">
          {files.map((f, i) => {
            const stray = !takesImages && isImage(f)
            return (
              <li key={`${f.name}-${i}`} title={stray ? `${model} cannot see images` : undefined} className={cn('inline-flex max-w-[220px] items-center gap-1.5 rounded-lg border border-line bg-surface-2 py-1 pr-1 pl-2 text-[12px] text-fg-2', stray && 'border-warn/40 text-fg-3 line-through')}>
                {isImage(f) ? <ImageIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
                <span className="truncate">{f.name}</span>
                <button type="button" onClick={() => setFiles((all) => all.filter((_, k) => k !== i))} aria-label={`Remove ${f.name}`} className="rounded p-0.5 text-fg-3 hover:bg-surface-3 hover:text-fg">
                  <X className="h-3 w-3" />
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {(refused || strayImages.length > 0) && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-warn/8 px-2.5 py-1.5 text-[12px] text-fg-2">
          <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-warn" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            {strayImages.length > 0 ? `${model} reads text only and cannot see the attached ${strayImages.length === 1 ? 'image' : 'images'}.` : refused}
            {' '}To send images, switch to a model that takes them.
          </span>
          {visionModel && (
            <Button variant="secondary" size="sm" onClick={() => choose({ model: visionModel.id, effort: visionModel.reasoning ? effort : 'off', context: visionModel.default_context ?? null })}>
              Switch to {visionModel.id}
            </Button>
          )}
          {strayImages.length > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setFiles((all) => all.filter((f) => !isImage(f)))}>Remove images</Button>
          )}
          {refused && !strayImages.length && (
            <button type="button" onClick={() => setRefused(null)} aria-label="Dismiss" className="rounded p-0.5 text-fg-3 hover:text-fg"><X className="h-3 w-3" /></button>
          )}
        </div>
      )}
      <textarea
        ref={areaRef}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          if (e.target.value && !loadedHere) warm(model, context)
        }}
        onKeyDown={onKeyDown}
        onPaste={(e) => addFiles(e.clipboardData.files)}
        placeholder={placeholder}
        aria-label="Message"
        rows={1}
        autoFocus={autoFocus}
        className="max-h-[280px] min-h-[44px] w-full resize-none bg-transparent px-1.5 py-1 text-[14px] leading-relaxed text-fg placeholder:text-fg-3 focus:outline-none"
      />
      <div className="flex items-center gap-1">
        <input ref={fileRef} type="file" multiple accept={takesImages ? `${FILE_ACCEPT},${IMAGE_ACCEPT}` : FILE_ACCEPT} className="hidden" onChange={(e) => {
          addFiles(e.target.files)
          e.target.value = ''
        }} />
        <input ref={imageRef} type="file" multiple accept={IMAGE_ACCEPT} className="hidden" onChange={(e) => {
          addFiles(e.target.files)
          e.target.value = ''
        }} />
        {onAttachMaps ? (
          <Popover label="Attach" width={250} align="start" estHeight={110}
            trigger={({ ref, open, toggle }) => (
              <Button ref={ref} variant="ghost" size="icon-sm" onClick={toggle} aria-expanded={open} aria-label="Attach" title="Attach files or research maps">
                <Paperclip />
              </Button>
            )}>
            {(close) => (
              <div className="grid py-1 text-[13px]">
                <button type="button" className="flex items-start gap-2.5 px-3 py-2 text-left hover:bg-surface-2" onClick={() => {
                  close()
                  fileRef.current?.click()
                }}>
                  <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
                  <span><span className="block text-fg">Files</span><span className="block text-[11.5px] text-fg-3">{takesImages ? 'PDFs, text files or images' : 'PDFs or text files'}</span></span>
                </button>
                <button type="button" className="flex items-start gap-2.5 px-3 py-2 text-left hover:bg-surface-2" onClick={() => {
                  close()
                  setMapError(null)
                  setPicking(true)
                }}>
                  <GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
                  <span><span className="block text-fg">Research map</span><span className="block text-[11.5px] text-fg-3">View it here; optionally give the model a summary</span></span>
                </button>
              </div>
            )}
          </Popover>
        ) : (
          <Button variant="ghost" size="icon-sm" onClick={() => fileRef.current?.click()} aria-label="Attach files"
            title={takesImages ? 'Attach PDFs, text files or images' : 'Attach PDFs or text files (read as text)'}>
            <Paperclip />
          </Button>
        )}
        <span title={takesImages ? 'Attach images' : `${model || 'This model'} reads text only. Switch to a model that takes images to attach them.`}>
          <Button variant="ghost" size="icon-sm" onClick={() => imageRef.current?.click()} aria-label="Attach images" disabled={!takesImages}
            className={cn(!takesImages && 'opacity-35')}>
            <ImageIcon />
          </Button>
        </span>
        <ModelPicker models={models.data} model={model} effort={effort} context={context} onChange={choose} />
        <span className="ml-auto" />
        {contextUsed && (context ?? current?.context) && (
          <ContextMeter used={contextUsed.tokens + Math.ceil(text.length / 4)} total={(context ?? current?.context)!} estimated={contextUsed.estimated} />
        )}
        {streaming ? (
          <Button variant="secondary" size="icon-sm" onClick={onStop} aria-label="Stop" title="Stop">
            <Square className="fill-current" />
          </Button>
        ) : (
          <Button type="submit" variant="primary" size="icon-sm" disabled={!text.trim() || !model || strayImages.length > 0} aria-label="Send"
            title={strayImages.length ? 'Remove the images or switch models first' : 'Send (Enter)'}>
            <ArrowUp />
          </Button>
        )}
      </div>
      {picking && (
        <MapPicker onClose={() => setPicking(false)} onAttach={(picks) => void attachMaps(picks)} attached={attachedMaps}
          busy={attaching} error={mapError} />
      )}
    </form>
  )
}
