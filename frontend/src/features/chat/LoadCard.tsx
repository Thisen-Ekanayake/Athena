import { Check, CircleAlert, Cpu, Loader2 } from 'lucide-react'
import type { LoadState } from '../../api/queries/chats'
import { cn } from '../../ui/cn'
import { tokens, megabytes, seconds } from './modelFormat'

function headline(s: LoadState) {
  const name = `${s.model} · ${tokens(s.context)} context`
  switch (s.status) {
    case 'loaded': return `${name} is ready`
    case 'waiting': return `Waiting for ${s.other ?? 'the other model'} to finish its current request`
    case 'swapping': return `Swapping ${s.other ?? 'the other model'} out for ${s.model}`
    case 'failed': return `${s.model} failed to load`
    case 'offline': return 'The model server is not answering'
    default: return `Loading ${name}`
  }
}

/** Where the model is going: "GPU · RTX 4060 · 33/33 layers · 6.1 GB VRAM" */
function deviceLine(s: LoadState) {
  const d = s.device
  if (d.kind === 'cpu') return `CPU · ${megabytes(d.ram_mb)} of memory`
  const gpu = d.gpu ? d.gpu.replace(/^NVIDIA (GeForce )?/, '') : 'GPU'
  if (d.kind === 'split') return `GPU + CPU · ${gpu} · ${d.gpu_layers}/${d.layers} layers on the GPU · ${megabytes(d.vram_mb)} VRAM, ${megabytes(d.ram_mb)} RAM`
  return `GPU · ${gpu} · ${d.gpu_layers}/${d.layers} layers · ${megabytes(d.vram_mb)} VRAM`
}

/**
 * A model on its way into memory: which device, the stages the router reports, and a bar timed from the last
 * load of the same model at the same context (the router has no percentage of its own, so the bar slows near the
 * end rather than claim to be done).
 */
export function LoadCard({ state, className }: { state: LoadState; className?: string }) {
  const failed = state.status === 'failed' || state.status === 'offline'
  const indeterminate = state.status === 'waiting' || state.status === 'swapping' || state.status === 'unloaded'
  const pct = Math.round((state.status === 'loaded' ? 1 : state.progress) * 100)
  return (
    <div role="status" aria-live="polite" className={cn('grid gap-2 rounded-xl border border-line bg-surface-2/60 px-3 py-2.5 text-[12.5px]', failed && 'border-bad/30', className)}>
      <div className="flex items-center gap-2">
        {failed ? <CircleAlert className="h-3.5 w-3.5 shrink-0 text-bad" aria-hidden="true" />
          : state.status === 'loaded' ? <Check className="h-3.5 w-3.5 shrink-0 text-good" aria-hidden="true" />
            : <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" aria-hidden="true" />}
        <span className="min-w-0 flex-1 truncate font-medium text-fg">{headline(state)}</span>
        {state.status === 'loading' && (
          <span className="shrink-0 font-mono text-[11.5px] text-fg-3">{state.eta_seconds > 0.5 ? `~${seconds(state.eta_seconds)} left` : 'almost there'}</span>
        )}
      </div>
      {!failed && (
        <p className="flex items-center gap-1.5 text-[11.5px] text-fg-3">
          <Cpu className="h-3 w-3 shrink-0" aria-hidden="true" />
          <span className="truncate">{deviceLine(state)}</span>
        </p>
      )}
      {!failed && (
        <div className="relative h-1.5 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-label="Loading the model"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={indeterminate ? undefined : pct}>
          {indeterminate ? (
            <span className="absolute inset-y-0 w-1/3 animate-[loadslide_1.4s_ease-in-out_infinite] rounded-full bg-accent/60" />
          ) : (
            <span className="absolute inset-y-0 left-0 rounded-full bg-accent transition-[width] duration-700 ease-linear" style={{ width: `${pct}%` }} />
          )}
        </div>
      )}
      <ol className="grid gap-0.5 text-[11.5px]">
        {state.stages.map((s) => (
          <li key={s.label} className={cn('flex items-center gap-1.5', s.state === 'pending' ? 'text-fg-3/70' : s.state === 'active' ? 'text-fg-2' : 'text-fg-3')}>
            {s.state === 'done' ? <Check className="h-3 w-3 text-good" aria-hidden="true" />
              : s.state === 'active' ? <span className="mx-[3px] h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
                : <span className="mx-[3px] h-1.5 w-1.5 rounded-full border border-fg-3/60" aria-hidden="true" />}
            {s.label}
          </li>
        ))}
      </ol>
      {state.status === 'offline' && <p className="text-[11.5px] text-fg-3">Start it with <span className="font-mono">./run_native.sh</span>, or ask an admin.</p>}
    </div>
  )
}
