import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, ChevronRight, TriangleAlert } from 'lucide-react'
import type { ChatModel, ChatModels, Effort, ModelContext } from '../../api/queries/chats'
import { Popover } from '../../ui/Popover'
import { cn } from '../../ui/cn'
import { contextHint, deviceText, seconds, speedText, tokens } from './modelFormat'

const EFFORTS: { id: Effort; label: string; hint: string }[] = [
  { id: 'off', label: 'Off', hint: 'Answers straight away' },
  { id: 'low', label: 'Low', hint: 'Thinks briefly first' },
  { id: 'medium', label: 'Medium', hint: 'Thinks it through' },
  { id: 'high', label: 'High', hint: 'Thinks longest; slowest' },
]

export interface ModelChoice {
  model: string
  effort: Effort
  /** The context size; null for a model without registry contexts */
  context: number | null
}

/** One line on what a model is and can do: "9B · Q4_K_M · thinks · images · tools". */
function describe(m: ChatModel) {
  return [m.params, m.quant, m.reasoning ? 'thinks' : null, m.vision ? 'images' : 'text only', m.tools ? 'tools' : null,
    m.contexts ? null : `${tokens(m.context)} context`].filter(Boolean).join(' · ')
}

/** A row that opens a menu beside the panel: "Context   16k · 38 tok/s  ›". */
function SubmenuRow({ label, value, open, onOpen }: { label: string; value: ReactNode; open: boolean; onOpen: (el: HTMLElement) => void }) {
  return (
    <button
      type="button"
      aria-haspopup="true"
      aria-expanded={open}
      onMouseEnter={(e) => onOpen(e.currentTarget)}
      onClick={(e) => onOpen(e.currentTarget)}
      onKeyDown={(e) => e.key === 'ArrowRight' && onOpen(e.currentTarget)}
      className={cn('mx-1 flex w-[calc(100%-0.5rem)] items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-fg hover:bg-surface-2', open && 'bg-surface-2')}
    >
      <span className="flex-1">{label}</span>
      <span className="truncate text-[12px] text-fg-3">{value}</span>
      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
    </button>
  )
}

/** A menu beside the picker's panel (right of it, or left when the screen ends), kept open by the Popover. */
function Flyout({ anchor, label, intro, children }: { anchor: HTMLElement; label: string; intro: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const width = 300
  useLayoutEffect(() => {
    const panel = anchor.closest('[role="dialog"]')?.getBoundingClientRect() ?? anchor.getBoundingClientRect()
    const row = anchor.getBoundingClientRect()
    const height = ref.current?.offsetHeight ?? 240
    const right = panel.right + 6
    const left = right + width > window.innerWidth - 8 ? Math.max(8, panel.left - width - 6) : right
    setPos({ left, top: Math.max(8, Math.min(row.top - 8, window.innerHeight - height - 8)) })
  }, [anchor])
  return createPortal(
    <div ref={ref} data-popover-keep="" className="fixed z-[71] rounded-xl border border-line bg-surface py-1 shadow-pop"
      style={{ width, top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}>
      <p className="px-3 pt-1.5 pb-1 text-[11.5px] leading-snug text-fg-3">{intro}</p>
      <div role="radiogroup" aria-label={label}>{children}</div>
    </div>,
    document.body,
  )
}

function Option({ selected, onPick, children, aside }: { selected: boolean; onPick: () => void; children: ReactNode; aside?: ReactNode }) {
  return (
    <button type="button" role="radio" aria-checked={selected} onClick={onPick}
      className="mx-1 flex w-[calc(100%-0.5rem)] items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-surface-2">
      <span className="min-w-0 flex-1">{children}</span>
      {aside}
      <span className="w-3.5 shrink-0">{selected && <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}</span>
    </button>
  )
}

function ContextOption({ c, selected, reloads, onPick }: { c: ModelContext; selected: boolean; reloads: boolean; onPick: () => void }) {
  return (
    <Option selected={selected} onPick={onPick} aside={
      <span className="shrink-0 font-mono text-[11.5px] text-fg-2" title={c.speed_source === 'measured' ? 'Measured on this machine' : 'Estimated until a benchmark or a few chats'}>
        {speedText(c)}
      </span>
    }>
      <span className="flex items-baseline gap-2">
        <span className="font-mono text-[13px] text-fg">{tokens(c.tokens)}</span>
        <span className="truncate text-[11.5px] text-fg-3">{contextHint(c.tokens)}</span>
      </span>
      <span className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-fg-3">
        <span className={cn(c.device === 'split' && 'text-warn')}>{deviceText(c)}</span>
        {!c.fits && <span className="inline-flex items-center gap-0.5 text-warn" title="May not fit in the GPU's memory"><TriangleAlert className="h-3 w-3" aria-hidden="true" />tight</span>}
        {c.device !== 'gpu' && c.prompt_tps != null && <span title="How fast it reads the prompt before answering">· reads {c.prompt_tps} tok/s</span>}
        {c.loaded ? <span className="text-good">· loaded</span> : reloads ? <span>· reloads in ~{seconds(c.load_seconds || 5)}</span> : null}
      </span>
    </Option>
  )
}

/** The model for the next message, with its context size and effort in menus beside it. */
export function ModelPicker({ models, model, effort, context, onChange, disabled }: {
  models: ChatModels | undefined
  model: string
  effort: Effort
  context: number | null
  onChange: (next: ModelChoice) => void
  disabled?: boolean
}) {
  const list: ChatModel[] = models?.models ?? []
  const current = list.find((m) => m.id === model)
  const thinks = current?.reasoning ?? false
  const contexts = current?.contexts ?? []
  const picked = contexts.find((c) => c.tokens === context) ?? contexts.find((c) => c.tokens === current?.default_context)
  const effortLabel = EFFORTS.find((e) => e.id === effort)?.label
  const budget = (id: Effort) => models?.efforts.find((e) => e.id === id)?.budget ?? 0

  const pickModel = (m: ChatModel) => onChange({
    model: m.id,
    effort: m.reasoning ? (effort === 'off' && !thinks ? models?.default_effort ?? 'low' : effort) : 'off',
    // Keep the size when the new model offers it; else its default
    context: m.contexts?.some((c) => c.tokens === context) ? context : m.default_context ?? null,
  })

  return (
    <Popover
      label="Model, context and effort"
      width={300}
      estHeight={380}
      align="start"
      trigger={({ ref, open, toggle }) => (
        <button
          ref={ref}
          type="button"
          onClick={toggle}
          disabled={disabled}
          aria-expanded={open}
          title="Model, context and effort"
          className={cn('inline-flex h-7 max-w-[300px] items-center gap-1.5 rounded-lg px-2 text-[12.5px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-50', open && 'bg-surface-2 text-fg')}
        >
          <span className="truncate font-mono">{model || 'model'}</span>
          {picked && <span className="shrink-0 text-fg-3">· {tokens(picked.tokens)}</span>}
          {thinks && <span className="shrink-0 text-fg-3">· {effort === 'off' ? 'no thinking' : effortLabel}</span>}
          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        </button>
      )}
    >
      {(close) => (
        <PickerPanel
          list={list} model={model} current={current} picked={picked} contexts={contexts} thinks={thinks} effort={effort}
          effortLabel={effortLabel} budget={budget} pickModel={(m) => { pickModel(m); close() }}
          pickContext={(c) => { onChange({ model, effort, context: c }); close() }}
          pickEffort={(e) => { onChange({ model, effort: e, context: picked?.tokens ?? null }); close() }}
          legacyVision={!models?.registry ? models?.vision_model : undefined}
        />
      )}
    </Popover>
  )
}

function PickerPanel({ list, model, current, picked, contexts, thinks, effort, effortLabel, budget, pickModel, pickContext, pickEffort, legacyVision }: {
  list: ChatModel[]
  model: string
  current: ChatModel | undefined
  picked: ModelContext | undefined
  contexts: ModelContext[]
  thinks: boolean
  effort: Effort
  effortLabel: string | undefined
  budget: (id: Effort) => number
  pickModel: (m: ChatModel) => void
  pickContext: (tokens: number) => void
  pickEffort: (e: Effort) => void
  legacyVision?: string
}) {
  const [sub, setSub] = useState<{ kind: 'context' | 'effort'; anchor: HTMLElement } | null>(null)
  const loadedAt = current?.loaded_context
  return (
    <div className="grid py-1" onMouseLeave={(e) => {
      // Leaving towards the flyout keeps it; leaving elsewhere closes it
      if (!(e.relatedTarget instanceof Element && e.relatedTarget.closest('[data-popover-keep]'))) setSub(null)
    }}>
      <div className="max-h-[260px] overflow-y-auto" role="radiogroup" aria-label="Model">
        {list.length === 0 && <p className="px-3 py-2 text-[12.5px] text-fg-3">The model server lists no models. Is it running?</p>}
        {list.map((m) => (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={m.id === model}
            onMouseEnter={() => setSub(null)}
            onClick={() => pickModel(m)}
            className="mx-1 flex w-[calc(100%-0.5rem)] items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-surface-2"
          >
            <span className="grid min-w-0 flex-1">
              <span className="flex items-center gap-1.5">
                <span className="truncate font-mono text-[13px] text-fg">{m.id}</span>
                {m.loaded && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-good" title="Loaded" aria-label="loaded" />}
              </span>
              <span className="truncate text-[11.5px] text-fg-3">{describe(m)}</span>
            </span>
            <span className="w-3.5 shrink-0">{m.id === model && <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}</span>
          </button>
        ))}
      </div>
      {(contexts.length > 0 || thinks) && <div className="my-1 border-t border-line" />}
      {contexts.length > 0 && picked && (
        <SubmenuRow label="Context" value={`${tokens(picked.tokens)} · ${speedText(picked)}`} open={sub?.kind === 'context'}
          onOpen={(anchor) => setSub({ kind: 'context', anchor })} />
      )}
      {thinks && (
        <SubmenuRow label="Effort" value={effort === 'off' ? 'Off' : effortLabel} open={sub?.kind === 'effort'}
          onOpen={(anchor) => setSub({ kind: 'effort', anchor })} />
      )}
      {current && !current.vision && current.contexts && (
        <p className="mx-3 mt-1 border-t border-line pt-2 pb-1 text-[11.5px] text-fg-3">{current.id} reads text and files only; pick a model with images to attach pictures.</p>
      )}
      {legacyVision && (
        <p className="mx-3 mt-1 border-t border-line pt-2 pb-1 text-[11.5px] text-fg-3">Messages with images go to <span className="font-mono">{legacyVision}</span>.</p>
      )}
      {sub?.kind === 'context' && (
        <Flyout anchor={sub.anchor} label="Context size" intro="How much the model reads at once: your files, sources and the conversation. Bigger reads more; smaller answers faster.">
          {contexts.map((c) => (
            <ContextOption key={c.tokens} c={c} selected={c.tokens === picked?.tokens} reloads={loadedAt != null && loadedAt !== c.tokens} onPick={() => pickContext(c.tokens)} />
          ))}
        </Flyout>
      )}
      {sub?.kind === 'effort' && (
        <Flyout anchor={sub.anchor} label="Effort" intro="Higher effort thinks longer before answering, so answers take longer.">
          {EFFORTS.map((e) => (
            <Option key={e.id} selected={e.id === effort} onPick={() => pickEffort(e.id)}>
              <span className="block text-[13px] text-fg">{e.label}</span>
              <span className="block text-[11.5px] text-fg-3">{e.hint}{budget(e.id) ? ` · up to ${tokens(budget(e.id))} thinking tokens` : ''}</span>
            </Option>
          ))}
        </Flyout>
      )}
    </div>
  )
}
