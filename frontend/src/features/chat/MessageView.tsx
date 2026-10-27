import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Brain, Check, ChevronRight, Copy, ExternalLink, FileText, Map as MapIcon, NotebookPen, Plus,
  RotateCcw, Search, TriangleAlert,
} from 'lucide-react'
import type { ArtifactRef } from '../../api/queries/artifacts'
import type { ChatMessage, ChatSource, LoadState, SearchResult, ToolStep, TurnStats } from '../../api/queries/chats'
import { fileUrl, useAddToProject } from '../../api/queries/projects'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { Markdown } from '../reviews/Markdown'
import { LoadCard } from './LoadCard'
import { DEVICE_LABEL, seconds as secs } from './modelFormat'

/** An assistant turn as the page shows it: saved, or still streaming (``live``). */
export interface AssistantTurn {
  id: string
  content: string
  reasoning: string | null
  reasoningMs: number | null
  thinking: boolean
  steps: ToolStep[]
  sources: ChatSource[]
  artifacts: ArtifactRef[]
  notices: string[]
  status: ChatMessage['status']
  error: string | null
  model: string | null
  effort: string | null
  tokens: number | null
  live: boolean
  /** The model's load while the turn waits for it */
  loading?: LoadState | null
  /** How the answer ran: speed, device, time to the first token */
  stats?: TurnStats | null
}

/** "38 tok/s · GPU · first token 0.4 s · loaded in 5.2 s" */
function statsText(s: TurnStats | null | undefined) {
  if (!s) return null
  const device = s.device === 'split' && s.gpu_layers != null ? `GPU + CPU (${s.gpu_layers}/${s.layers} layers)` : s.device ? DEVICE_LABEL[s.device] : null
  return [
    s.tps ? `${s.tps >= 10 ? Math.round(s.tps) : s.tps} tok/s` : null,
    device,
    s.ttft_ms != null ? `first token ${secs(s.ttft_ms / 1000)}` : null,
    s.load_ms ? `loaded in ${secs(s.load_ms / 1000)}` : null,
  ].filter(Boolean).join(' · ')
}

export function UserMessage({ content, attachments }: { content: string; attachments: ChatMessage['attachments'] }) {
  return (
    <div className="flex flex-col items-end gap-1.5">
      {attachments.length > 0 && (
        <ul className="flex flex-wrap justify-end gap-1.5">
          {attachments.map((a) => (
            <li key={a.id}>
              {a.kind === 'image' ? (
                <a href={fileUrl(a.id)} target="_blank" rel="noopener noreferrer" title={a.filename}>
                  <img src={fileUrl(a.id)} alt={a.filename} className="h-24 max-w-[200px] rounded-lg border border-line object-cover" />
                </a>
              ) : (
                <a href={fileUrl(a.id)} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-[240px] items-center gap-1.5 rounded-lg border border-line bg-surface px-2 py-1 text-[12px] text-fg-2 hover:text-fg">
                  <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                  <span className="truncate">{a.filename}</span>
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-surface-2 px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap text-fg shadow-[0_0_0_1px_var(--line)]">
        {content}
      </div>
    </div>
  )
}

const seconds = (ms: number) => (ms < 1000 ? 'under a second' : `${Math.round(ms / 1000)} s`)

function Thinking({ text, ms, live }: { text: string; ms: number | null; live: boolean }) {
  const [open, setOpen] = useState(false)
  const last = text.trim().split('\n').filter(Boolean).slice(-1)[0] ?? ''
  return (
    <div className="grid gap-1.5">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex items-center gap-1.5 justify-self-start text-[12.5px] text-fg-3 hover:text-fg-2">
        <Brain className={cn('h-3.5 w-3.5', live && 'animate-pulse text-accent')} aria-hidden="true" />
        {live ? 'Thinking…' : `Thought for ${seconds(ms ?? 0)}`}
        <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} aria-hidden="true" />
      </button>
      {open ? (
        <div className="max-h-72 overflow-y-auto border-l-2 border-line pl-3 text-[12.5px] leading-relaxed whitespace-pre-wrap text-fg-3">{text}</div>
      ) : live && last ? (
        <p className="truncate border-l-2 border-line pl-3 text-[12.5px] text-fg-3">{last}</p>
      ) : null}
    </div>
  )
}

const STEP_ICONS: Record<string, typeof Search> = {
  search_papers: Search, query_map: MapIcon, write_artifact: NotebookPen, read_artifact: FileText, edit_artifact: NotebookPen,
}

function AddResult({ result, projectId }: { result: SearchResult; projectId: string }) {
  const add = useAddToProject()
  const [added, setAdded] = useState(result.in_project)
  if (added) return <span className="inline-flex items-center gap-1 text-[11.5px] text-good"><Check className="h-3 w-3" aria-hidden="true" />In project</span>
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={add.isPending}
      onClick={() => add.mutate(
        { projectId, item: result.item_id ? { kind: 'paper', id: result.item_id } : { kind: 'paper', meta: result.meta ?? { title: result.title } } },
        { onSuccess: () => setAdded(true) },
      )}
      title="Add to this project"
    >
      {add.isPending ? <Spinner className="h-3 w-3" /> : <Plus />} Add
    </Button>
  )
}

function Step({ step, projectId }: { step: ToolStep; projectId: string | null }) {
  const [open, setOpen] = useState(false)
  const Icon = STEP_ICONS[step.tool] ?? Search
  const query = typeof step.args.query === 'string' ? step.args.query : typeof step.args.question === 'string' ? step.args.question : null
  const results = step.results ?? []
  return (
    <li className="grid gap-1">
      <button
        type="button"
        onClick={() => results.length && setOpen((o) => !o)}
        className={cn('inline-flex min-w-0 items-center gap-2 justify-self-start rounded-lg border border-line bg-surface px-2.5 py-1 text-[12.5px] text-fg-2', results.length > 0 && 'hover:border-line-strong hover:text-fg')}
        aria-expanded={results.length ? open : undefined}
      >
        {step.status === 'running' ? <Spinner className="h-3.5 w-3.5" /> : step.status === 'failed'
          ? <TriangleAlert className="h-3.5 w-3.5 text-warn" aria-hidden="true" />
          : <Icon className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}
        <span className="truncate">{step.summary ?? `${step.label}${query ? `: ${query}` : ''}`}</span>
        {results.length > 0 && <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 transition-transform', open && 'rotate-90')} aria-hidden="true" />}
      </button>
      {open && (
        <ul className="grid gap-1 rounded-lg border border-line bg-surface p-2">
          {results.map((r) => (
            <li key={r.n} className="flex items-start gap-2 text-[12.5px]">
              <span className="w-6 shrink-0 font-mono text-[11.5px] text-fg-3">[{r.n}]</span>
              <span className="min-w-0 flex-1">
                {r.item_id ? (
                  <Link to={`/items/${r.item_id}`} className="text-fg hover:underline">{r.title}</Link>
                ) : r.url ? (
                  <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-fg hover:underline">{r.title}</a>
                ) : <span className="text-fg">{r.title}</span>}
                <span className="block text-[11.5px] text-fg-3">{[r.authors.join(', '), r.year, r.item_id ? 'in Athena' : r.source].filter(Boolean).join(' · ')}</span>
              </span>
              {projectId && <AddResult result={r} projectId={projectId} />}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function Sources({ sources, messageId, open, onToggle }: { sources: ChatSource[]; messageId: string; open: boolean; onToggle: () => void }) {
  return (
    <div className="grid gap-1.5">
      <button type="button" onClick={onToggle} aria-expanded={open} className="inline-flex items-center gap-1 justify-self-start text-[12px] text-fg-3 hover:text-fg-2">
        <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} aria-hidden="true" />
        {sources.length} {sources.length === 1 ? 'source' : 'sources'}
      </button>
      {open && (
        <ol className="grid gap-1.5">
          {sources.map((s) => {
            const external = s.link?.startsWith('http')
            const title = s.link ? (external
              ? <a href={s.link} target="_blank" rel="noopener noreferrer" className="text-fg hover:underline">{s.title}<ExternalLink className="ml-1 inline h-3 w-3 text-fg-3" aria-hidden="true" /></a>
              : <Link to={s.link} className="text-fg hover:underline">{s.title}</Link>) : <span className="text-fg">{s.title}</span>
            return (
              <li key={s.n} id={`src-${messageId}-${s.n}`} className="flex gap-2 rounded-lg px-1.5 py-1 text-[12.5px] transition-colors target:bg-accent-soft">
                <span className="w-6 shrink-0 font-mono text-[11.5px] text-fg-3">[{s.n}]</span>
                <span className="min-w-0 flex-1">
                  {title}
                  <span className="block text-[11.5px] text-fg-3">{[s.kind === 'map' ? `map ${s.map ?? ''}` : s.kind, s.section].filter(Boolean).join(' · ')}</span>
                  {s.excerpt && <span className="mt-0.5 line-clamp-2 block text-[12px] text-fg-3">{s.excerpt}</span>}
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

export function ArtifactCard({ artifact, onOpen }: { artifact: ArtifactRef; onOpen: (id: string) => void }) {
  return (
    <button type="button" onClick={() => onOpen(artifact.id)} className="flex w-full max-w-sm items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2.5 text-left transition-colors hover:border-accent-line">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-ink"><NotebookPen className="h-4 w-4" aria-hidden="true" /></span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-fg">{artifact.title}</span>
        <span className="block text-[11.5px] text-fg-3">Artifact · version {artifact.version} · click to open</span>
      </span>
    </button>
  )
}

export function AssistantMessage({ turn, projectId, onOpenArtifact, onRetry }: {
  turn: AssistantTurn
  projectId: string | null
  onOpenArtifact: (id: string) => void
  onRetry?: () => void
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const cite = (n: number) => {
    setSourcesOpen(true)
    requestAnimationFrame(() => {
      const el = document.getElementById(`src-${turn.id}-${n}`)
      el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      el?.classList.add('bg-accent-soft')
      setTimeout(() => el?.classList.remove('bg-accent-soft'), 1500)
    })
  }
  const waiting = turn.live && !turn.content && !turn.reasoning && turn.steps.length === 0
  return (
    <div className="grid gap-2.5">
      {turn.notices.map((n, i) => (
        <p key={i} className="flex items-start gap-1.5 text-[12px] text-warn"><TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{n}</p>
      ))}
      {turn.reasoning && <Thinking text={turn.reasoning} ms={turn.reasoningMs} live={turn.thinking} />}
      {turn.steps.length > 0 && (
        <ul className="grid gap-1.5" aria-label="Tools used">
          {turn.steps.map((s) => <Step key={s.id} step={s} projectId={projectId} />)}
        </ul>
      )}
      {waiting && turn.loading && turn.loading.status !== 'loaded' && <LoadCard state={turn.loading} className="max-w-md" />}
      {waiting && !(turn.loading && turn.loading.status !== 'loaded') && <Spinner label={turn.sources.length ? 'Reading the project…' : 'Waiting for the model…'} />}
      {turn.content && <Markdown text={turn.content} onCite={turn.sources.length ? cite : undefined} />}
      {turn.live && turn.content && <span className="h-3 w-1.5 animate-pulse bg-accent" aria-hidden="true" />}
      {turn.artifacts.length > 0 && (
        <div className="grid gap-1.5">{turn.artifacts.map((a) => <ArtifactCard key={a.id} artifact={a} onOpen={onOpenArtifact} />)}</div>
      )}
      {turn.error && <p className="flex items-start gap-1.5 text-[12.5px] text-bad"><TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{turn.error}</p>}
      {turn.status === 'stopped' && !turn.live && <p className="text-[12px] text-fg-3">Stopped.</p>}
      {turn.sources.length > 0 && <Sources sources={turn.sources} messageId={turn.id} open={sourcesOpen} onToggle={() => setSourcesOpen((o) => !o)} />}
      {!turn.live && (
        <div className="flex items-center gap-1 text-[11.5px] text-fg-3">
          {turn.content && (
            <Button variant="ghost" size="icon-sm" aria-label="Copy" title="Copy" onClick={() => {
              void navigator.clipboard?.writeText(turn.content)
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }}>
              {copied ? <Check /> : <Copy />}
            </Button>
          )}
          {onRetry && <Button variant="ghost" size="icon-sm" aria-label="Answer again" title="Answer again" onClick={onRetry}><RotateCcw /></Button>}
          <span className="ml-1 font-mono">{[turn.model, turn.effort && turn.effort !== 'off' ? `${turn.effort} effort` : null, turn.tokens ? `${turn.tokens.toLocaleString()} tokens` : null].filter(Boolean).join(' · ')}</span>
          {statsText(turn.stats) && <span className="font-mono text-fg-3/80" title="How this answer ran">· {statsText(turn.stats)}</span>}
        </div>
      )}
    </div>
  )
}
