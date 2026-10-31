import { useState } from 'react'
import { Brain, Check, ChevronDown, CircleStop, Eye, Gauge, Pause, Play, Plus, Power, RefreshCw, Star, Trash2, Type, Wrench } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { usePauseBackground } from '../../api/queries/modelActivity'
import {
  useBenchmark, useLoadModel, useMakeDefault, useRegistry, useRemoveModel, useUnloadModel, useUpdateModel, type GpuInfo, type Registry,
  type Reembed, type RegistryModel,
} from '../../api/queries/modelRegistry'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Popover } from '../../ui/Popover'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
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

/** Which context sizes users may pick (ticks, up to what the model was trained for) and the default. */
function ContextsEditor({ m, onSave, saving }: { m: RegistryModel; onSave: (contexts: number[], fallback: number) => void; saving: boolean }) {
  const [chosen, setChosen] = useState<number[]>(m.contexts.map((c) => c.tokens))
  const [fallback, setFallback] = useState(m.default_context)
  const fallbackNow = chosen.includes(fallback) ? fallback : chosen[0]
  const toggle = (c: number) => setChosen((all) => (all.includes(c) ? all.filter((x) => x !== c) : [...all, c].sort((a, b) => a - b)))
  return (
    <form className="grid gap-2 rounded-lg border border-line bg-surface-2/40 p-3" onSubmit={(e) => {
      e.preventDefault()
      if (chosen.length) onSave(chosen, fallbackNow)
    }}>
      <p className="text-[11.5px] text-fg-3">
        Sizes users may pick, up to the {tokens(m.info.context_train ?? 0)} it was trained for. Each is a preset of its own; large ones split onto the CPU and run slower.
      </p>
      <ul className="flex flex-wrap gap-1.5" aria-label="Context sizes">
        {m.context_steps.map((c) => {
          const on = chosen.includes(c)
          return (
            <li key={c} className={cn('flex items-center gap-2 rounded-lg border px-2 py-1 text-[12px]', on ? 'border-accent-line bg-accent-soft text-fg' : 'border-line text-fg-3')}>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={on} onChange={() => toggle(c)} className="accent-[var(--accent)]" aria-label={`Offer ${tokens(c)}`} />
                <span className="font-mono">{tokens(c)}</span>
              </label>
              <label className="flex items-center gap-1 text-[11px] text-fg-3" title="New chats start at this size; background work uses it">
                <input type="radio" name={`default-${m.id}`} checked={fallbackNow === c} disabled={!on} onChange={() => setFallback(c)} className="accent-[var(--accent)]" />
                default
              </label>
            </li>
          )
        })}
      </ul>
      <div><Button type="submit" size="sm" disabled={saving || !chosen.length}>{saving ? 'Saving…' : 'Save sizes'}</Button></div>
    </form>
  )
}

function statusDot(m: RegistryModel) {
  if (!m.complete || !m.exists) return <span className="h-2 w-2 shrink-0 rounded-full bg-bad" title="Cannot load" />
  if (!m.enabled) return <span className="h-2 w-2 shrink-0 rounded-full bg-fg-3/40" title="Off" />
  if (m.loaded) return <span className="h-2 w-2 shrink-0 rounded-full bg-good" title="Loaded" />
  return <span className="h-2 w-2 shrink-0 rounded-full border border-fg-3/60" title="Not loaded" />
}

/** The registry's models in a menu; the page shows the one picked. */
function ModelSelect({ models, selected, onSelect }: { models: RegistryModel[]; selected: RegistryModel; onSelect: (id: string) => void }) {
  const group = (role: RegistryModel['role']) => models.filter((m) => m.role === role)
  return (
    <Popover label="Registered models" width={360} estHeight={420} align="start" trigger={({ ref, open, toggle }) => (
      <button ref={ref} type="button" onClick={toggle} aria-expanded={open} title="Pick a model to see and change"
        className={cn('flex h-9 min-w-0 max-w-full items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 text-left hover:border-line-strong', open && 'border-line-strong')}>
        {statusDot(selected)}
        <span className="truncate font-mono text-[13px] text-fg">{selected.name}</span>
        {selected.is_default && <Chip tone="accent">default</Chip>}
        <span className="truncate text-[11.5px] text-fg-3">{[selected.info.params, selected.info.quant, bytes(selected.size_bytes)].filter(Boolean).join(' · ')}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
      </button>
    )}>
      {(close) => (
        <div className="grid max-h-[420px] overflow-y-auto py-1">
          {(['chat', 'embed'] as const).map((role) => group(role).length > 0 && (
            <div key={role} role="radiogroup" aria-label={role === 'chat' ? 'Chat models' : 'Embedding models'}>
              <p className="px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide text-fg-3 uppercase">{role === 'chat' ? 'Chat' : 'Embeddings'}</p>
              {group(role).map((m) => (
                <button key={m.id} type="button" role="radio" aria-checked={m.id === selected.id} onClick={() => { onSelect(m.id); close() }}
                  className="mx-1 flex w-[calc(100%-0.5rem)] items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-surface-2">
                  {statusDot(m)}
                  <span className="grid min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate font-mono text-[12.5px] text-fg">{m.name}</span>
                      {m.is_default && <Chip tone="accent">default</Chip>}
                      {!m.complete && <Chip tone="bad">incomplete</Chip>}
                      {!m.enabled && m.complete && <Chip>off</Chip>}
                    </span>
                    <span className="truncate text-[11px] text-fg-3">
                      {[m.info.params, m.info.quant, bytes(m.size_bytes), m.vision ? 'images' : m.role === 'chat' ? 'text only' : null, m.loaded ? 'loaded' : null].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  {m.id === selected.id && <Check className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </Popover>
  )
}

/** After an unload: background work that keeps using the model loads it straight back, unless it is paused. */
function ReloadWarning({ name, by }: { name: string; by: string[] }) {
  const pause = usePauseBackground()
  const list = by.length > 1 ? `${by.slice(0, -1).join(', ')} and ${by[by.length - 1]}` : by[0]
  return (
    <Notice tone="warn" title={`${list} will load ${name} again`}>
      <div className="grid justify-items-start gap-2">
        <p>{name} was unloaded, but {by.length > 1 ? 'they' : 'it'} used it in the last two minutes and the router loads it back for the next request. Pause background work to keep it out of memory; resume it under Model activity.</p>
        {pause.isSuccess ? <p className="text-good">Background work is paused.</p> : (
          <Button variant="secondary" size="sm" disabled={pause.isPending} onClick={() => pause.mutate({ pause: true })}><Pause />Pause background work</Button>
        )}
      </div>
    </Notice>
  )
}

/** After a switch of embedding model: what is still to be embedded again. */
function ReembedNotice({ r }: { r: Reembed }) {
  const left = [
    r.feed_left && `${r.feed_left.toLocaleString()} feed ${r.feed_left === 1 ? 'item' : 'items'}`,
    r.maps_left && `${r.maps_left.toLocaleString()} map passages and abstracts`,
    r.projects_left && `${r.projects_left.toLocaleString()} project ${r.projects_left === 1 ? 'file' : 'files'}`,
  ].filter(Boolean).join(', ')
  return (
    <Notice tone="info" title={`Embedding everything again with ${r.model}`}>
      {r.previous ? `Switched from ${r.previous}` : 'Switched'}{r.by ? ` by ${r.by}` : ''} on {new Date(r.since * 1000).toLocaleString()}.
      {' '}Left: {left}. Search, related papers and project chats find what is embedded so far; background work does
      this between chats, and a pause holds it.
    </Notice>
  )
}

function ModelDetail({ m, benchmarking }: { m: RegistryModel; benchmarking: Registry['benchmark'] }) {
  const update = useUpdateModel()
  const remove = useRemoveModel()
  const bench = useBenchmark()
  const makeDefault = useMakeDefault()
  const unload = useUnloadModel()
  const load = useLoadModel()
  const [editing, setEditing] = useState(false)
  const running = benchmarking?.state === 'running' && benchmarking.model_id === m.id
  const error = update.error ?? remove.error ?? bench.error ?? makeDefault.error ?? unload.error ?? load.error
  const embedder = m.role === 'embed'
  const defaultLabel = embedder ? 'default embedding model' : 'default chat model'
  const info = m.info
  const lastFailed = m.last_benchmark && m.last_benchmark.state !== 'running' && m.last_benchmark.error
  const usable = m.complete && m.exists
  const turnOff = () => {
    const note = m.is_default ? `${m.name} is the ${defaultLabel}. Turning it off unloads it and makes another chat model the default.`
      : `Turn ${m.name} off? It is unloaded now and chats stop offering it.`
    if (window.confirm(note)) update.mutate({ id: m.id, enabled: false })
  }
  const makeDefaultNow = () => {
    // Vectors from two models cannot be compared, so a new embedder means embedding everything again.
    if (embedder && !window.confirm(`Make ${m.name} the embedding model? Every stored vector is thrown away and made again `
      + 'with it: the feed, the maps and project files. That takes hours on the GPU; until it is done, search, related '
      + 'papers and project chats only find what has been embedded again.')) return
    makeDefault.mutate(m.id)
  }
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="grid min-w-0 flex-1 gap-1">
          <p className="flex flex-wrap items-center gap-1.5">
            <Chip>{m.role === 'chat' ? 'Chat' : 'Embeddings'}</Chip>
            {m.is_default && <Chip tone="accent">{defaultLabel}</Chip>}
            {m.role === 'chat' && (m.vision ? <Chip tone="accent"><Eye />images</Chip> : <Chip><Type />text only</Chip>)}
            {m.reasoning && <Chip><Brain />thinks</Chip>}
            {m.role === 'chat' && m.tools && <Chip><Wrench />tools</Chip>}
            {m.used_for.filter((u) => u !== 'default chat model' && !(embedder && u === 'embeddings')).map((u) => <Chip key={u} tone="good">{u}</Chip>)}
            {m.loaded && <Chip tone="good">loaded</Chip>}
            {!m.enabled && <Chip tone="warn">off</Chip>}
            {!m.exists && <Chip tone="bad">file missing</Chip>}
            {!m.complete && m.exists && <Chip tone="bad">file incomplete</Chip>}
            {m.changed && <Chip tone="warn">file changed</Chip>}
          </p>
          <p className="text-[11.5px] text-fg-3">
            {[info.architecture, info.params, info.quant, `${m.layers - 1} layers`, info.context_train ? `trained for ${tokens(info.context_train)}` : null, bytes(m.size_bytes), m.mmproj_bytes ? `+ ${bytes(m.mmproj_bytes)} projector` : null].filter(Boolean).join(' · ')}
          </p>
          <p className="truncate font-mono text-[11px] text-fg-3/80" title={m.path}>{m.path}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {!m.is_default && usable && (
            <Button variant="secondary" size="sm" disabled={makeDefault.isPending} onClick={makeDefaultNow}
              title={embedder ? 'Every vector comes from it: switching embeds everything again' : 'New chats start with it; summaries and Q&A use it'}>
              <Star />{makeDefault.isPending && embedder ? 'Checking it answers…' : 'Make default'}
            </Button>
          )}
          {m.loaded ? (
            <Button variant="ghost" size="sm" disabled={unload.isPending} onClick={() => unload.mutate(m.id)} title="Free its GPU or CPU memory now; it loads again when needed">
              <CircleStop />Unload
            </Button>
          ) : m.enabled && usable && (
            <Button variant="ghost" size="sm" disabled={load.isPending} onClick={() => load.mutate(m.id)}
              title={`Load it${embedder ? '' : ` at ${tokens(m.default_context)}`} now; the router swaps out the model it holds`}>
              <Play />Load
            </Button>
          )}
          <Button variant="ghost" size="sm" disabled={running || bench.isPending || !m.enabled || !usable} onClick={() => bench.mutate({ id: m.id, force: m.benchmarked })}
            title={!usable ? 'The file cannot be loaded' : embedder ? 'Time a batch of passages: how many tokens a second it reads'
              : m.benchmarked ? 'Measure every context again' : 'Measure the contexts not measured yet'}>
            <Gauge className={cn(running && 'animate-pulse')} />{running ? `Benchmarking ${benchmarking?.step}/${benchmarking?.of}` : m.benchmarked ? 'Re-benchmark' : 'Benchmark'}
          </Button>
          <Button variant="ghost" size="sm" disabled={update.isPending || (embedder && m.is_default && m.enabled)}
            onClick={() => (m.enabled ? turnOff() : update.mutate({ id: m.id, enabled: true }))}
            title={embedder && m.is_default && m.enabled ? 'Every vector comes from it; make another embedding model the default first'
              : m.enabled ? 'Turn off: unloads it, and chats stop offering it' : 'Turn on'}>
            <Power />{m.enabled ? 'Turn off' : 'Turn on'}
          </Button>
          <Button variant="ghost" size="icon-sm" disabled={remove.isPending} aria-label={`Remove ${m.name}`} title="Remove from the registry (the file stays)"
            onClick={() => window.confirm(`Remove ${m.name} from the registry? The file stays where it is.${m.is_default ? ' Another chat model becomes the default.' : ''}`) && remove.mutate(m.id)}>
            <Trash2 />
          </Button>
        </div>
      </div>
      {!m.complete && m.exists && (
        <Notice tone="error" title="The file is incomplete, so llama.cpp cannot load it">
          It holds {bytes(m.size_bytes)} of the {bytes(m.needed_bytes)} its weights need; a download was probably cut short. Download it again, then turn the model on.
        </Notice>
      )}
      {unload.data && unload.data.reloaded_by.length > 0 && <ReloadWarning name={m.name} by={unload.data.reloaded_by} />}
      {lastFailed && usable && (
        <Notice tone="warn" title="The last benchmark did not finish">{m.last_benchmark?.error}</Notice>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label={`Where ${m.name} loads`} value={m.placement} options={PLACEMENTS} onChange={(placement) => update.mutate({ id: m.id, placement })} />
        {m.role === 'chat' && <Button variant="ghost" size="sm" onClick={() => setEditing((e) => !e)}>{editing ? 'Close' : 'Context sizes'}</Button>}
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
                {embedder ? (
                  <td className="py-1 pr-3" title={c.prompt_tps ? 'Tokens read a second, from a benchmark' : 'Not measured yet: benchmark it'}>
                    {c.prompt_tps ? `${Math.round(c.prompt_tps).toLocaleString()} tok/s read` : '—'}
                  </td>
                ) : (
                  <td className="py-1 pr-3" title={c.speed_source === 'measured' ? `Measured (${c.samples} runs)` : 'Estimated'}>{speedText(c)}</td>
                )}
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
    </div>
  )
}

/**
 * The model registry: the GGUF files the local model server serves, where each loads at each context and how fast
 * it answers there. Settings → Models and keys.
 */
export function ModelRegistryCard() {
  const [adding, setAdding] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)
  // After an add, Athena measures and benchmarks the model: keep the numbers fresh for a while.
  const [polling, setPolling] = useState(false)
  const registry = useRegistry(polling)
  const data = registry.data
  if (registry.isLoading) return <Card className="p-4"><Spinner label="Reading the model registry…" /></Card>
  if (!data) return <Notice tone="error" title="The registry could not be read">{apiErrorMessage(registry.error, 'Try again in a moment.')}</Notice>
  const bench = data.benchmark
  const selected = data.models.find((m) => m.id === picked) ?? data.models.find((m) => m.is_default && m.role === 'chat') ?? data.models[0]
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
        {data.reembed && !data.reembed.done && <ReembedNotice r={data.reembed} />}
      </div>
      <div className="grid gap-4 p-4">
        <div className="flex flex-wrap items-center gap-2">
          {selected && <ModelSelect models={data.models} selected={selected} onSelect={setPicked} />}
          <span className="text-[12px] text-fg-3">{data.models.length} {data.models.length === 1 ? 'model' : 'models'}</span>
          <Button variant="primary" size="sm" className="ml-auto" disabled={!data.writable} onClick={() => setAdding(true)}><Plus />Add model</Button>
        </div>
        {selected ? <ModelDetail key={selected.id} m={selected} benchmarking={bench} /> : <p className="text-[12.5px] text-fg-3">No models yet. Add one from a folder on this machine.</p>}
      </div>
      {adding && <AddModelDialog onClose={(addedId) => {
        setAdding(false)
        if (addedId) {
          setPicked(addedId)
          setPolling(true)
          setTimeout(() => setPolling(false), 120_000)
        }
      }} />}
    </Card>
  )
}
