import { Brain, Check, ChevronDown, Cpu, Image as ImageIcon } from 'lucide-react'
import type { ChatModel, ChatModels, Effort } from '../../api/queries/chats'
import { Popover } from '../../ui/Popover'
import { cn } from '../../ui/cn'

const EFFORTS: { id: Effort; label: string; hint: string }[] = [
  { id: 'off', label: 'Off', hint: 'Answers straight away' },
  { id: 'low', label: 'Low', hint: 'Thinks briefly first' },
  { id: 'medium', label: 'Medium', hint: 'Thinks it through' },
  { id: 'high', label: 'High', hint: 'Thinks longest; slowest' },
]

const tokens = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))

/** The model for the next message and, for a model that thinks, how hard it thinks (its effort). */
export function ModelPicker({ models, model, effort, onChange, disabled }: {
  models: ChatModels | undefined
  model: string
  effort: Effort
  onChange: (next: { model: string; effort: Effort }) => void
  disabled?: boolean
}) {
  const list: ChatModel[] = models?.models ?? []
  const current = list.find((m) => m.id === model)
  const thinks = current?.reasoning ?? false
  const budget = (id: Effort) => models?.efforts.find((e) => e.id === id)?.budget ?? 0
  const label = EFFORTS.find((e) => e.id === effort)?.label

  return (
    <Popover
      label="Model and effort"
      width={280}
      estHeight={320}
      align="start"
      trigger={({ ref, open, toggle }) => (
        <button
          ref={ref}
          type="button"
          onClick={toggle}
          disabled={disabled}
          aria-expanded={open}
          title="Model and effort"
          className={cn('inline-flex h-7 max-w-[260px] items-center gap-1.5 rounded-lg px-2 text-[12.5px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-50', open && 'bg-surface-2 text-fg')}
        >
          <span className="truncate font-mono">{model || 'model'}</span>
          {thinks && <span className="text-fg-3">· {effort === 'off' ? 'no thinking' : label}</span>}
          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        </button>
      )}
    >
      {(close) => (
        <div className="grid">
          <p className="border-b border-line px-3 py-2 text-[12px] text-fg-3">Model</p>
          <div className="max-h-48 overflow-y-auto py-1" role="radiogroup" aria-label="Model">
            {list.length === 0 && <p className="px-3 py-2 text-[12.5px] text-fg-3">The model server lists no models. Is it running?</p>}
            {list.map((m) => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={m.id === model}
                onClick={() => onChange({ model: m.id, effort: m.reasoning ? (effort === 'off' && !thinks ? models?.default_effort ?? 'low' : effort) : 'off' })}
                className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left hover:bg-surface-2"
              >
                <Cpu className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[12.5px] text-fg">{m.id}</span>
                  <span className="flex items-center gap-2 text-[11px] text-fg-3">
                    {tokens(m.context)} context
                    {m.reasoning && <span className="inline-flex items-center gap-0.5"><Brain className="h-3 w-3" aria-hidden="true" />thinks</span>}
                    {m.vision && <span className="inline-flex items-center gap-0.5"><ImageIcon className="h-3 w-3" aria-hidden="true" />images</span>}
                    {m.loaded && <span className="text-good">loaded</span>}
                  </span>
                </span>
                {m.id === model && <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}
              </button>
            ))}
          </div>
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
                      onChange({ model, effort: e.id })
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
          {models?.vision_model && (
            <p className="border-t border-line px-3 py-2 text-[11.5px] text-fg-3">
              Messages with images go to <span className="font-mono">{models.vision_model}</span>.
            </p>
          )}
        </div>
      )}
    </Popover>
  )
}
