import { useState } from 'react'
import { Brain, Eye, Gauge, Plus, Power, RefreshCw, Trash2, Type, Wrench } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import {
  useBenchmark, useRegistry, useRemoveModel, useUpdateModel, type GpuInfo, type Registry, type RegistryModel,
} from '../../api/queries/modelRegistry'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { PLACEMENTS, bytes, deviceText, megabytes, seconds, speedText, tokens } from '../chat/modelFormat'
import { AddModelDialog } from './AddModelDialog'

/** The card's memory: what other programs hold, what the model server holds, what is free, and the margin. */
function GpuBar({ gpu, margin }: { gpu: GpuInfo; margin: number }) {
  const pct = (mb: number) => `${Math.max(0, Math.min(100, (mb / gpu.total_mb) * 100))}%`
  const free = Math.max(gpu.total_mb - gpu.used_mb, 0)
  return (
    <div className="grid gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[12.5px]">
        <span className="font-medium text-fg">{gpu.name}</span>
        <span className="font-mono text-[11.5px] text-fg-3">{megabytes(gpu.total_mb)} · a model may use {megabytes(gpu.available_mb)}</span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-surface-3" role="img"
        aria-label={`Other programs ${megabytes(gpu.others_mb)}, models ${megabytes(gpu.llama_mb)}, free ${megabytes(free)}`}>
        <span className="h-full bg-fg-3/60" style={{ width: pct(gpu.others_mb) }} />
        <span className="h-full bg-accent" style={{ width: pct(gpu.llama_mb) }} />
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11.5px] text-fg-3">
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-fg-3/60" />Other programs {megabytes(gpu.others_mb)}</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-accent" />Loaded model {megabytes(gpu.llama_mb)}</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-surface-3 ring-1 ring-line" />Free {megabytes(free)}</span>
        <span>{megabytes(margin)} kept free for the desktop</span>
      </p>
      {gpu.stray && gpu.stray.length > 0 && (
        <Notice tone="warn" title="A llama-server outside Athena’s routers holds GPU memory">
          {gpu.stray.map((p) => `pid ${p.pid} (${megabytes(p.mb)})`).join(', ')}. Until it stops, models load on the CPU. It is
          usually an old server still shutting down; if it stays, stop it with <code>kill {gpu.stray.map((p) => p.pid).join(' ')}</code>.
        </Notice>
      )}
    </div>
  )
}

function Servers({ data }: { data: Registry }) {
  const { gpu, cpu } = data.servers
  const cpuWanted = data.models.some((m) => m.enabled && m.contexts.some((c) => c.server === 'cpu'))
  return (
    <div className="grid gap-2">
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-fg-3">
        <span className="inline-flex items-center gap-1.5">
          <span className={cn('h-2 w-2 rounded-full', gpu.online ? 'bg-good' : 'bg-bad')} aria-hidden="true" />
          GPU router <span className="font-mono">{gpu.url.replace(/^https?:\/\//, '').replace(/\/v1$/, '')}</span>
          {gpu.loaded.length > 0 && <span>· holds <span className="font-mono">{gpu.loaded.join(', ')}</span></span>}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className={cn('h-2 w-2 rounded-full', cpu.online ? 'bg-good' : cpuWanted ? 'bg-bad' : 'bg-fg-3/50')} aria-hidden="true" />
          CPU router <span className="font-mono">{cpu.url.replace(/^https?:\/\//, '').replace(/\/v1$/, '')}</span>
          {cpu.loaded.length > 0 && <span>· holds <span className="font-mono">{cpu.loaded.join(', ')}</span></span>}
        </span>
      </p>
      {gpu.online && !gpu.serves_registry && (
        <Notice tone="warn" title="The model server is running from the old preset file">
          It does not know <span className="font-mono">{gpu.missing.join(', ')}</span>. Restart it with <code>./run_native.sh --stop</code> then{' '}
          <code>./run_native.sh</code>, which starts it from <code>config/llama-router.generated.ini</code>.
        </Notice>
      )}
      {cpuWanted && !cpu.online && (
        <Notice tone="warn" title="The CPU router is not running">
          Models placed on the CPU are served on a second router. Restart with <code>./run_native.sh</code> to start it.
        </Notice>
      )}
    </div>
  )
}

/** Context sizes as an editable list in thousands: "8, 16, 32". */
function ContextsEditor({ m, onSave, saving }: { m: RegistryModel; onSave: (contexts: number[], fallback: number) => void; saving: boolean }) {
  const [text, setText] = useState(m.contexts.map((c) => Math.round(c.tokens / 1024)).join(', '))
  const [fallback, setFallback] = useState(m.default_context)
  const parsed = Array.from(new Set(text.split(/[\s,]+/).map((t) => Math.round(Number(t) * 1024)).filter((n) => n >= 512))).sort((a, b) => a - b)
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
      e.preventDefault()
      if (parsed.length) onSave(parsed, parsed.includes(fallback) ? fallback : parsed[0])
    }}>
      <label className="grid gap-1">
        <span className="text-[11.5px] text-fg-3">Context sizes, in thousands of tokens</span>
        <input value={text} onChange={(e) => setText(e.target.value)} className={cn(inputClass, 'h-7 w-56 font-mono text-[12px]')} />
      </label>
      <label className="grid gap-1">
        <span className="text-[11.5px] text-fg-3">Default</span>
        <select value={fallback} onChange={(e) => setFallback(Number(e.target.value))} className={cn(inputClass, 'h-7 text-[12px]')}>
          {parsed.map((c) => <option key={c} value={c}>{tokens(c)}</option>)}
        </select>
      </label>
      <Button type="submit" size="sm" disabled={saving || !parsed.length}>{saving ? 'Saving…' : 'Save sizes'}</Button>
    </form>
  )
}

function ModelRow({ m, benchmarking }: { m: RegistryModel; benchmarking: Registry['benchmark'] }) {
  const update = useUpdateModel()
  const remove = useRemoveModel()
  const bench = useBenchmark()
  const [editing, setEditing] = useState(false)
  const running = benchmarking?.state === 'running' && benchmarking.model_id === m.id
  const error = update.error ?? remove.error ?? bench.error
  const info = m.info
  return (
    <li className={cn('grid gap-3 px-4 py-3.5', !m.enabled && 'opacity-60')}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="grid min-w-0 flex-1 gap-1">
          <p className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[13px] font-medium text-fg">{m.name}</span>
            <Chip>{m.role === 'chat' ? 'Chat' : 'Embeddings'}</Chip>
            {m.role === 'chat' && (m.vision
              ? <Chip tone="accent"><Eye />images</Chip>
              : <Chip><Type />text only</Chip>)}
            {m.reasoning && <Chip><Brain />thinks</Chip>}
            {m.role === 'chat' && m.tools && <Chip><Wrench />tools</Chip>}
            {m.used_for.map((u) => <Chip key={u} tone="good">{u}</Chip>)}
            {!m.enabled && <Chip tone="warn">off</Chip>}
            {!m.exists && <Chip tone="bad">file missing</Chip>}
            {m.changed && <Chip tone="warn">file changed</Chip>}
          </p>
          <p className="text-[11.5px] text-fg-3">
            {[info.architecture, info.params, info.quant, `${m.layers - 1} layers`, bytes(m.size_bytes), m.mmproj_bytes ? `+ ${bytes(m.mmproj_bytes)} projector` : null].filter(Boolean).join(' · ')}
          </p>
          <p className="truncate font-mono text-[11px] text-fg-3/80" title={m.path}>{m.path}</p>
        </div>
        <div className="flex items-center gap-1">
          {m.role === 'chat' && (
            <Button variant="ghost" size="sm" disabled={running || bench.isPending || !m.enabled} onClick={() => bench.mutate({ id: m.id, force: m.benchmarked })}
              title={m.benchmarked ? 'Measure every context again' : 'Measure the contexts not measured yet'}>
              <Gauge className={cn(running && 'animate-pulse')} />{running ? `Benchmarking ${benchmarking?.step}/${benchmarking?.of}` : m.benchmarked ? 'Re-benchmark' : 'Benchmark'}
            </Button>
          )}
          <Button variant="ghost" size="icon-sm" disabled={update.isPending || m.used_for.length > 0} onClick={() => update.mutate({ id: m.id, enabled: !m.enabled })}
            aria-label={m.enabled ? `Turn ${m.name} off` : `Turn ${m.name} on`} title={m.used_for.length ? `Used for ${m.used_for.join(', ')}` : m.enabled ? 'Turn off: chats stop offering it' : 'Turn on'}>
            <Power />
          </Button>
          <Button variant="ghost" size="icon-sm" disabled={remove.isPending || m.used_for.length > 0} aria-label={`Remove ${m.name}`}
            title={m.used_for.length ? `Used for ${m.used_for.join(', ')}: point those at another model first` : 'Remove from the registry (the file stays)'}
            onClick={() => window.confirm(`Remove ${m.name} from the registry? The file stays where it is.`) && remove.mutate(m.id)}>
            <Trash2 />
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label={`Where ${m.name} loads`} value={m.placement} options={PLACEMENTS} onChange={(placement) => update.mutate({ id: m.id, placement })} />
        {m.role === 'chat' && <Button variant="ghost" size="sm" onClick={() => setEditing((e) => !e)}>{editing ? 'Close' : 'Edit context sizes'}</Button>}
      </div>
      {editing && <ContextsEditor m={m} saving={update.isPending} onSave={(contexts, fallback) => update.mutate({ id: m.id, contexts, default_context: fallback }, { onSuccess: () => setEditing(false) })} />}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-[12px]">
          <thead className="text-left text-[11px] text-fg-3">
            <tr>
              <th className="py-1 pr-3 font-normal">Context</th>
              <th className="py-1 pr-3 font-normal">Loads on</th>
              <th className="py-1 pr-3 font-normal">VRAM</th>
              <th className="py-1 pr-3 font-normal">RAM</th>
              <th className="py-1 pr-3 font-normal">Speed</th>
              <th className="py-1 pr-3 font-normal">Load</th>
              <th className="py-1 font-normal">Now</th>
            </tr>
          </thead>
          <tbody className="font-mono text-fg-2">
            {m.contexts.map((c) => (
              <tr key={c.tokens} className="border-t border-line/60">
                <td className="py-1 pr-3 text-fg">{tokens(c.tokens)}{c.tokens === m.default_context && <span className="ml-1.5 font-sans text-[11px] text-fg-3">default</span>}</td>
                <td className={cn('py-1 pr-3 font-sans', c.device === 'split' && 'text-warn', !c.fits && 'text-bad')} title={c.measured ? 'Projected by llama-fit-params' : 'Estimated from the file until measured'}>
                  {deviceText(c, true)}{!c.measured && ' ~'}{!c.fits && ' · may not fit'}
                </td>
                <td className="py-1 pr-3">{c.vram_mb ? megabytes(c.vram_mb) : '—'}</td>
                <td className="py-1 pr-3">{c.ram_mb ? megabytes(c.ram_mb) : '—'}</td>
                <td className="py-1 pr-3" title={c.speed_source === 'measured' ? `Measured (${c.samples} runs)` : 'Estimated'}>{m.role === 'chat' ? speedText(c) : '—'}</td>
                <td className="py-1 pr-3">{c.load_seconds ? seconds(c.load_seconds) : '—'}</td>
                <td className="py-1 font-sans text-[11.5px]">
                  {c.status === 'loaded' ? <span className="text-good">loaded</span> : c.status === 'loading' ? <span className="text-accent">loading</span>
                    : c.status === 'failed' ? <span className="text-bad">failed</span> : c.status ? <span className="text-fg-3">idle</span> : <span className="text-fg-3">not served</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <p className="text-[12px] text-bad">{apiErrorMessage(error, 'That did not work.')}</p>}
    </li>
  )
}

/**
 * The model registry: the GGUF files the local model server serves, where each loads at each context and how fast
 * it answers there. Settings → Models and keys.
 */
export function ModelRegistryCard() {
  const [adding, setAdding] = useState(false)
  // After an add, Athena measures and benchmarks the model: keep the numbers fresh for a while.
  const [polling, setPolling] = useState(false)
  const registry = useRegistry(polling)
  const data = registry.data
  if (registry.isLoading) return <Card className="p-4"><Spinner label="Reading the model registry…" /></Card>
  if (!data) return <Notice tone="error" title="The registry could not be read">{apiErrorMessage(registry.error, 'Try again in a moment.')}</Notice>
  const bench = data.benchmark
  return (
    <Card className="grid gap-0 overflow-hidden">
      <div className="grid gap-4 border-b border-line p-4">
        {data.gpu ? <GpuBar gpu={data.gpu} margin={data.margin_mb} /> : <p className="text-[12.5px] text-fg-3">No NVIDIA GPU found: every model runs on the CPU.</p>}
        <Servers data={data} />
        {!data.writable && <Notice tone="info" title="Read only here">{data.read_only_reason}</Notice>}
        {!data.fit_tool && data.writable && (
          <p className="text-[11.5px] text-fg-3">llama-fit-params was not found beside llama-server, so memory is estimated from each file’s header.</p>
        )}
        {bench?.state === 'running' && (
          <p className="flex items-center gap-2 text-[12.5px] text-fg-2">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden="true" />
            Benchmarking <span className="font-mono">{bench.model}</span> at {tokens(bench.context ?? 0)} ({bench.step} of {bench.of}); chats go first and pause it.
          </p>
        )}
        <div className="flex items-center justify-between gap-3">
          <p className="text-[12.5px] text-fg-3">{data.models.length} {data.models.length === 1 ? 'model' : 'models'} · each context size is a preset of its own, loaded when first used</p>
          <Button variant="primary" size="sm" disabled={!data.writable} onClick={() => setAdding(true)}><Plus />Add model</Button>
        </div>
      </div>
      <ul className="divide-y divide-line">
        {data.models.map((m) => <ModelRow key={m.id} m={m} benchmarking={bench} />)}
      </ul>
      {adding && <AddModelDialog onClose={() => {
        setAdding(false)
        setPolling(true)
        setTimeout(() => setPolling(false), 120_000)
      }} />}
    </Card>
  )
}
