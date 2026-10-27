import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowUp, Brain, ChevronRight, Eye, File, Folder, FolderPlus, HardDrive, Wrench, X } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { inspectModel, useAddFolder, useAddModel, useBrowse, type Inspection, type Placement } from '../../api/queries/modelRegistry'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { PLACEMENTS, bytes, deviceText, megabytes, tokens } from '../chat/modelFormat'

const STEPS = [4096, 8192, 16384, 32768, 65536, 131072]

/** Folders and .gguf files on the server, inside the folders models may come from. */
function Browser({ onPick, picked }: { onPick: (path: string) => void; picked: string | null }) {
  const [path, setPath] = useState<string | null>(null)
  const [folder, setFolder] = useState('')
  const browse = useBrowse(path)
  const addFolder = useAddFolder()
  const data = browse.data
  return (
    <div className="grid min-h-0 grid-rows-[auto_1fr_auto] gap-2">
      <div className="flex min-w-0 items-center gap-1.5 text-[12px] text-fg-3">
        <Button variant="ghost" size="icon-sm" disabled={!data?.path} onClick={() => setPath(data?.parent ?? null)} aria-label="Up a folder" title="Up a folder"><ArrowUp /></Button>
        <HardDrive className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate font-mono" title={data?.path ?? undefined}>{data?.path ?? 'Folders models may come from'}</span>
      </div>
      <ul className="min-h-[220px] overflow-y-auto rounded-lg border border-line bg-surface-2/40 py-1" aria-label="Files">
        {browse.isLoading && <li className="px-3 py-2"><Spinner label="Reading the folder…" /></li>}
        {browse.isError && <li className="px-3 py-2 text-[12.5px] text-bad">{apiErrorMessage(browse.error, 'The folder could not be read.')}</li>}
        {data?.entries.length === 0 && <li className="px-3 py-2 text-[12.5px] text-fg-3">No folders or .gguf files here.</li>}
        {data?.entries.map((e) => (
          <li key={e.path}>
            <button
              type="button"
              onClick={() => (e.kind === 'dir' ? setPath(e.path) : onPick(e.path))}
              disabled={e.kind === 'mmproj'}
              title={e.kind === 'mmproj' ? 'A vision projector: pick its model, then choose this as its projector' : e.path}
              className={cn('flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] hover:bg-surface-2 disabled:cursor-default disabled:opacity-60',
                picked === e.path && 'bg-accent-soft')}
            >
              {e.kind === 'dir' ? <Folder className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" /> : e.kind === 'mmproj'
                ? <Eye className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" /> : <File className="h-3.5 w-3.5 shrink-0 text-fg-2" aria-hidden="true" />}
              <span className={cn('min-w-0 flex-1 truncate', e.kind !== 'dir' && 'font-mono')}>{e.name}</span>
              {e.kind === 'mmproj' && <span className="text-[11px] text-fg-3">projector</span>}
              {e.parts && e.parts > 1 && <span className="text-[11px] text-fg-3">{e.parts} parts</span>}
              {e.size_bytes != null && <span className="shrink-0 font-mono text-[11.5px] text-fg-3">{bytes(e.size_bytes)}</span>}
              {e.kind === 'dir' && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />}
            </button>
          </li>
        ))}
      </ul>
      <form className="flex items-center gap-1.5" onSubmit={(e) => {
        e.preventDefault()
        if (folder.trim()) addFolder.mutate(folder.trim(), { onSuccess: () => { setPath(folder.trim()); setFolder('') } })
      }}>
        <FolderPlus className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
        <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Models elsewhere? Add a folder, e.g. /data/gguf" aria-label="Add a folder" className={cn(inputClass, 'h-7 flex-1 font-mono text-[12px]')} />
        <Button type="submit" size="sm" disabled={!folder.trim() || addFolder.isPending}>Add folder</Button>
      </form>
      {addFolder.isError && <p className="text-[12px] text-bad">{apiErrorMessage(addFolder.error, 'That folder could not be added.')}</p>}
    </div>
  )
}

/** The form for one picked file: name, projector, abilities, placement and the context sizes users may pick. */
function Details({ seen, onDone }: { seen: Inspection; onDone: () => void }) {
  const add = useAddModel()
  const info = seen.info
  const [name, setName] = useState(seen.name)
  const [role, setRole] = useState<'chat' | 'embed'>(info.role ?? 'chat')
  const [mmproj, setMmproj] = useState<string>(seen.projectors.find((p) => p.match)?.path ?? '')
  const [reasoning, setReasoning] = useState(seen.reasoning)
  const [toolsOn, setToolsOn] = useState(seen.tools)
  const [placement, setPlacement] = useState<Placement>('auto')
  const trained = info.context_train ?? 32768
  const steps = Array.from(new Set([...STEPS.filter((s) => s <= trained), ...seen.contexts])).sort((a, b) => a - b)
  const [contexts, setContexts] = useState<number[]>(seen.contexts)
  const [fallback, setFallback] = useState(seen.default_context)
  const preview = new Map(seen.preview.map((p) => [p.tokens, p]))
  const defaultContext = contexts.includes(fallback) ? fallback : contexts[0]

  const toggle = (c: number) => setContexts((all) => (all.includes(c) ? all.filter((x) => x !== c) : [...all, c].sort((a, b) => a - b)))
  const check = (label: string, value: boolean, set: (v: boolean) => void, icon: ReactNode, hint: string) => (
    <label className="flex items-start gap-2 text-[12.5px] text-fg-2" title={hint}>
      <input type="checkbox" checked={value} onChange={(e) => set(e.target.checked)} className="mt-0.5 accent-[var(--accent)]" />
      <span className="inline-flex items-center gap-1">{icon}{label}</span>
    </label>
  )

  return (
    <form className="grid content-start gap-3" onSubmit={(e) => {
      e.preventDefault()
      add.mutate({
        path: info.path, name: name.trim(), role, mmproj_path: role === 'chat' && mmproj ? mmproj : null, reasoning, tools: toolsOn,
        placement, contexts: role === 'chat' ? contexts : undefined, default_context: role === 'chat' ? defaultContext : undefined,
      }, { onSuccess: onDone })
    }}>
      <div className="grid gap-1">
        <p className="truncate font-mono text-[12.5px] text-fg" title={info.path}>{info.filename}</p>
        <p className="flex flex-wrap gap-1.5">
          {[info.architecture, info.params, info.quant, info.layers ? `${info.layers} layers` : null, info.context_train ? `trained for ${tokens(info.context_train)}` : null, bytes(info.size_bytes)]
            .filter(Boolean).map((t) => <Chip key={String(t)}>{t}</Chip>)}
        </p>
        {seen.already && <p className="text-[12px] text-warn">This file is already registered; add it again only to serve it under another name.</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1">
          <span className="text-[12px] text-fg-3">Name (what chats and settings call it)</span>
          <input value={name} onChange={(e) => setName(e.target.value)} className={cn(inputClass, 'font-mono')} required pattern="[a-z0-9][a-z0-9._\-]*" />
        </label>
        <label className="grid gap-1">
          <span className="text-[12px] text-fg-3">Used for</span>
          <select value={role} onChange={(e) => setRole(e.target.value as 'chat' | 'embed')} className={inputClass}>
            <option value="chat">Chat</option>
            <option value="embed">Embeddings</option>
          </select>
        </label>
      </div>
      {role === 'chat' && (
        <>
          <label className="grid gap-1">
            <span className="text-[12px] text-fg-3">Vision projector (lets it read images)</span>
            <select value={mmproj} onChange={(e) => setMmproj(e.target.value)} className={inputClass}>
              <option value="">None: text only</option>
              {seen.projectors.map((p) => (
                <option key={p.path} value={p.path}>{p.filename} · {bytes(p.size_bytes)}{p.match ? ' · made for this model' : ''}</option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap gap-x-5 gap-y-1.5">
            {check('Thinks', reasoning, setReasoning, <Brain className="h-3.5 w-3.5" aria-hidden="true" />, 'Chats offer an effort (a thinking budget)')}
            {check('Takes tools', toolsOn, setToolsOn, <Wrench className="h-3.5 w-3.5" aria-hidden="true" />, 'Its template handles tool calls: paper search, maps, artifacts')}
          </div>
          <div className="grid gap-1.5">
            <span className="text-[12px] text-fg-3">Context sizes users may pick (the selected one is the default)</span>
            <ul className="grid gap-1" aria-label="Context sizes">
              {steps.map((c) => {
                const p = preview.get(c)
                const on = contexts.includes(c)
                return (
                  <li key={c} className={cn('flex items-center gap-2 rounded-lg px-2 py-1 text-[12.5px]', on ? 'bg-surface-2' : 'text-fg-3')}>
                    <input type="checkbox" checked={on} onChange={() => toggle(c)} aria-label={`Offer ${tokens(c)}`} className="accent-[var(--accent)]" />
                    <span className="w-10 font-mono">{tokens(c)}</span>
                    <span className="min-w-0 flex-1 truncate text-[11.5px] text-fg-3">
                      {p ? `${deviceText(p, true)} · ${p.vram_mb ? `${megabytes(p.vram_mb)} VRAM` : `${megabytes(p.ram_mb)} RAM`}` : 'estimated after adding'}
                    </span>
                    <label className="flex items-center gap-1 text-[11.5px] text-fg-3">
                      <input type="radio" name="default-context" checked={defaultContext === c} disabled={!on} onChange={() => setFallback(c)} className="accent-[var(--accent)]" />
                      default
                    </label>
                  </li>
                )
              })}
            </ul>
            <p className="text-[11.5px] text-fg-3">Estimated from the file; Athena measures memory and speed for each size once it is added.</p>
          </div>
        </>
      )}
      <div className="grid gap-1">
        <span className="text-[12px] text-fg-3">Where it loads</span>
        <Segmented label="Where it loads" value={placement} options={PLACEMENTS} onChange={setPlacement} />
      </div>
      {add.isError && <p className="text-[12.5px] text-bad">{apiErrorMessage(add.error, 'The model could not be added.')}</p>}
      <div className="flex justify-end gap-2">
        <Button type="submit" variant="primary" disabled={add.isPending || !name.trim() || (role === 'chat' && contexts.length === 0)}>
          {add.isPending ? 'Adding…' : 'Add model'}
        </Button>
      </div>
    </form>
  )
}

/** Pick a GGUF file on the server and register it. */
export function AddModelDialog({ onClose }: { onClose: () => void }) {
  const [picked, setPicked] = useState<string | null>(null)
  const [seen, setSeen] = useState<Inspection | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    dialogRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const pick = (path: string) => {
    setPicked(path)
    setSeen(null)
    setError(null)
    setBusy(true)
    inspectModel(path).then(setSeen).catch((e) => setError(apiErrorMessage(e, 'That file could not be read.'))).finally(() => setBusy(false))
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-bg/60 p-4 backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="add-model-title"
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col rounded-xl border border-line bg-surface shadow-pop focus:outline-none">
        <header className="flex items-center gap-3 border-b border-line px-4 py-3">
          <h2 id="add-model-title" className="flex-1 text-[14px] font-semibold text-fg">Add a model</h2>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close"><X /></Button>
        </header>
        <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <Browser onPick={pick} picked={picked} />
          <div className="min-w-0">
            {!picked && (
              <Notice title="Pick a .gguf file">
                Files are read where they are on this machine; nothing is copied. A model split into parts shows once. Pair a model with a
                vision projector (an <code>mmproj</code> file) to let it read images.
              </Notice>
            )}
            {busy && <Spinner label="Reading the file’s header…" />}
            {error && <Notice tone="error" title="Not a model llama.cpp can load">{error}</Notice>}
            {seen && <Details key={seen.info.path} seen={seen} onDone={onClose} />}
          </div>
        </div>
      </div>
    </div>
  )
}
