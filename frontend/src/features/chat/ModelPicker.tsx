import { Brain, Check, ChevronDown, Cpu, FileText, Image as ImageIcon, TriangleAlert, Type, Wrench } from 'lucide-react'
import type { ReactNode } from 'react'
import type { ChatModel, ChatModels, Effort, ModelContext } from '../../api/queries/chats'
import { Popover } from '../../ui/Popover'
import { cn } from '../../ui/cn'
import { bytes, contextHint, deviceText, seconds, speedText, tokens } from './modelFormat'

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

/** What a model can do, as small labels: thinks, images or text only, tools, files. */
function Abilities({ m }: { m: ChatModel }) {
  const item = (icon: ReactNode, label: string, title: string, tone?: 'muted') => (
    <span title={title} className={cn('inline-flex items-center gap-0.5', tone === 'muted' && 'text-fg-3/70')}>{icon}{label}</span>
  )
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-fg-3">
      {m.reasoning && item(<Brain className="h-3 w-3" aria-hidden="true" />, 'thinks', 'Thinks before answering; pick how hard below')}
      {m.vision
        ? item(<ImageIcon className="h-3 w-3" aria-hidden="true" />, 'images', 'Reads images you attach')
        : item(<Type className="h-3 w-3" aria-hidden="true" />, 'text only', 'Cannot see images; switch to a model with images for those', 'muted')}
      {item(<FileText className="h-3 w-3" aria-hidden="true" />, 'files', 'Reads PDFs and text files as text, as much as its context holds')}
      {m.tools && item(<Wrench className="h-3 w-3" aria-hidden="true" />, 'tools', 'Searches papers, asks your maps and writes artifacts')}
    </span>
  )
}

function ContextRow({ c, selected, onPick }: { c: ModelContext; selected: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onPick}
      className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left hover:bg-surface-2"
    >
      <span className="w-9 shrink-0 font-mono text-[12.5px] text-fg">{tokens(c.tokens)}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[11.5px] text-fg-2">{contextHint(c.tokens)}</span>
        <span className="flex items-center gap-1.5 text-[11px] text-fg-3">
          <span className={cn(c.device === 'split' && 'text-warn', c.device === 'cpu' && 'text-fg-3')}>{deviceText(c)}</span>
          {!c.fits && <span className="inline-flex items-center gap-0.5 text-warn" title="May not fit in the GPU's memory"><TriangleAlert className="h-3 w-3" aria-hidden="true" />tight</span>}
          {c.loaded && <span className="text-good">loaded</span>}
        </span>
      </span>
      <span className="shrink-0 text-right font-mono text-[11.5px] text-fg-2" title={c.speed_source === 'measured' ? 'Measured on this machine' : 'Estimated; becomes exact after a benchmark or a few chats'}>
        {speedText(c)}
      </span>
      <span className="w-3.5 shrink-0">{selected && <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}</span>
    </button>
  )
}

/** The model for the next message, its context size (with where it loads and how fast it answers) and effort. */
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
  const budget = (id: Effort) => models?.efforts.find((e) => e.id === id)?.budget ?? 0
  const label = EFFORTS.find((e) => e.id === effort)?.label
  const contexts = current?.contexts ?? []
  const picked = contexts.find((c) => c.tokens === context) ?? contexts.find((c) => c.tokens === current?.default_context)
  const reload = picked && !picked.loaded && current?.loaded

  const pickModel = (m: ChatModel) => onChange({
    model: m.id,
    effort: m.reasoning ? (effort === 'off' && !thinks ? models?.default_effort ?? 'low' : effort) : 'off',
    // Keep the size when the new model offers it; else its default
    context: m.contexts?.some((c) => c.tokens === context) ? context : m.default_context ?? null,
  })

  return (
    <Popover
      label="Model, context and effort"
      width={340}
      estHeight={560}
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
          {thinks && <span className="shrink-0 text-fg-3">· {effort === 'off' ? 'no thinking' : label}</span>}
          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        </button>
      )}
    >
      {(close) => (
        <div className="grid max-h-[min(560px,80vh)] overflow-y-auto">
          <p className="border-b border-line px-3 py-2 text-[12px] text-fg-3">Model</p>
          <div className="py-1" role="radiogroup" aria-label="Model">
            {list.length === 0 && <p className="px-3 py-2 text-[12.5px] text-fg-3">The model server lists no models. Is it running?</p>}
            {list.map((m) => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={m.id === model}
                onClick={() => pickModel(m)}
                className="flex w-full items-start gap-2.5 px-3 py-1.5 text-left hover:bg-surface-2"
              >
                <Cpu className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="flex items-baseline gap-2">
                    <span className="truncate font-mono text-[12.5px] text-fg">{m.id}</span>
                    {m.loaded && <span className="shrink-0 text-[11px] text-good">loaded{m.loaded_context ? ` · ${tokens(m.loaded_context)}` : ''}</span>}
                  </span>
                  {(m.params || m.quant || m.size_bytes) && (
                    <span className="text-[11px] text-fg-3">{[m.params, m.quant, m.size_bytes ? bytes(m.size_bytes) : null].filter(Boolean).join(' · ')}</span>
                  )}
                  {!m.contexts && <span className="text-[11px] text-fg-3">{tokens(m.context)} context</span>}
                  <Abilities m={m} />
                </span>
                {m.id === model && <Check className="mt-0.5 h-3.5 w-3.5 text-accent" aria-hidden="true" />}
              </button>
            ))}
          </div>
          {contexts.length > 0 && (
            <>
              <p className="flex items-center justify-between border-y border-line px-3 py-2 text-[12px] text-fg-3">
                <span>Context</span>
                <span className="text-[11px]">bigger reads more · smaller is faster</span>
              </p>
              <div className="py-1" role="radiogroup" aria-label="Context size">
                {contexts.map((c) => (
                  <ContextRow key={c.tokens} c={c} selected={c.tokens === picked?.tokens} onPick={() => onChange({ model, effort, context: c.tokens })} />
                ))}
              </div>
              {reload && (
                <p className="px-3 pb-2 text-[11.5px] text-fg-3">
                  Switching to {tokens(picked.tokens)} reloads the model (about {seconds(picked.load_seconds || 5)}); it starts as soon as you pick.
                </p>
              )}
            </>
          )}
          {thinks && (
            <>
              <p className="border-y border-line px-3 py-2 text-[12px] text-fg-3">Effort</p>
              <div className="grid py-1" role="radiogroup" aria-label="Effort">
                {EFFORTS.map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    role="radio"
                    aria-checked={e.id === effort}
                    onClick={() => {
                      onChange({ model, effort: e.id, context: picked?.tokens ?? null })
                      close()
                    }}
                    className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left hover:bg-surface-2"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] text-fg">{e.label}</span>
                      <span className="block text-[11.5px] text-fg-3">{e.hint}{budget(e.id) ? ` · up to ${tokens(budget(e.id))} thinking tokens` : ''}</span>
                    </span>
                    {e.id === effort && <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}
                  </button>
                ))}
              </div>
            </>
          )}
          {!models?.registry && models?.vision_model && (
            <p className="border-t border-line px-3 py-2 text-[11.5px] text-fg-3">
              Messages with images go to <span className="font-mono">{models.vision_model}</span>.
            </p>
          )}
        </div>
      )}
    </Popover>
  )
}
