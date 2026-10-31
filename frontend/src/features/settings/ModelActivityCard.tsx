import { useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import {
  useModelActivity, usePauseBackground, type Activity, type ActivityServer, type FeatureToday, type ModelCall, type Slot,
  type Swap,
} from '../../api/queries/modelActivity'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Pager } from '../../ui/Pager'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { deviceText, megabytes, seconds, tokens } from '../chat/modelFormat'

const count = (n: number | null | undefined) => (n ?? 0).toLocaleString()

/** 42 -> "42 s ago", 300 -> "5 min ago" */
function ago(now: number, at: number) {
  const s = Math.max(0, now - at)
  if (s < 60) return `${Math.round(s)} s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  return `${Math.round(s / 3600)} h ago`
}

const duration = (s: number) => (s < 60 ? seconds(s) : s < 3600 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${(s / 3600).toFixed(1)} h`)

/** Who asked for a call: the person, else background work (summaries, embeddings, a map's lane) or the system. */
const requester = (c: ModelCall) => c.user ?? (c.user_id ? 'Former user' : c.background ? 'Background task' : 'System')

const HOLDERS: Record<string, string> = {
  chat: 'A chat has the model: background work waits until it ends.',
  benchmark: 'A benchmark is running: background work waits between batches.',
}

/**
 * Pause or resume background work, a group at a time (the feed's work, the maps' work) or all of it, with who paused
 * it and when. A chat holds every group by itself (the lane's holder) and lets go when the chat ends; the buttons are
 * for the rest of the time.
 */
function PauseControl({ data }: { data: Activity }) {
  const toggle = usePauseBackground()
  const groups = data.lane.groups
  const holder = data.lane.holder
  const pausedCount = groups.filter((g) => g.paused).length
  const all = pausedCount === groups.length
  const held = holder ? (holder === 'benchmark' ? 'for a benchmark' : 'for a chat') : null
  const summary = all ? 'All background work is paused. Chats, Q&A, reviews and search still run.'
    : pausedCount ? `${groups.filter((g) => g.paused).map((g) => g.label).join(' and ')} paused; the rest ${held ? `is held ${held}` : 'runs'}.`
      : held ? `Background work is held ${held} and carries on by itself when it ends.`
        : 'Background work runs.'
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="flex min-w-0 flex-1 items-center gap-2 text-[12.5px] text-fg-2">
          <span className={cn('h-2 w-2 shrink-0 rounded-full', pausedCount ? 'bg-warn' : held ? 'bg-accent' : 'bg-good')} aria-hidden="true" />
          <span>{summary}</span>
        </p>
        <Button variant={all ? 'primary' : 'secondary'} size="sm" disabled={toggle.isPending} onClick={() => toggle.mutate({ pause: !all })}
          title={all ? 'Let all background work use the models again' : 'Hold all background work until you resume, so an unloaded model stays out of memory. A call already running finishes.'}>
          {all ? <><Play />Resume all</> : <><Pause />Pause all</>}
        </Button>
      </div>
      <ul className="grid gap-2" aria-label="Background work">
        {groups.map((g) => {
          const queued = data.queues.filter((q) => q.group === g.key).reduce((n, q) => n + q.count, 0)
          return (
            <li key={g.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-line/70 px-3 py-2">
              <div className="grid min-w-0 flex-1 gap-0.5">
                <p className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                  <span className="font-medium text-fg">{g.label}</span>
                  <span className={cn('text-[11.5px]', g.paused ? 'text-warn' : held ? 'text-accent' : 'text-good')}>
                    {g.paused ? `paused${g.paused.by ? ` by ${g.paused.by}` : ''}, ${ago(data.now, g.paused.since).replace(' ago', '')}` : held ? `held ${held}` : 'runs'}
                  </span>
                  {queued > 0 && <span className="text-[11.5px] text-fg-3">{count(queued)} queued</span>}
                </p>
                <p className="text-[11.5px] text-fg-3">{g.covers[0].toUpperCase() + g.covers.slice(1)}</p>
              </div>
              <Button variant={g.paused ? 'primary' : 'ghost'} size="sm" disabled={toggle.isPending} aria-label={`${g.paused ? 'Resume' : 'Pause'} ${g.label}`}
                onClick={() => toggle.mutate({ pause: !g.paused, group: g.key })}>
                {g.paused ? <><Play />Resume</> : <><Pause />Pause</>}
              </Button>
            </li>
          )
        })}
      </ul>
      {toggle.isError && <p className="text-[12px] text-bad">{apiErrorMessage(toggle.error, 'That did not work.')}</p>}
    </div>
  )
}

function Bar({ value, of, tone = 'accent', label }: { value: number; of: number; tone?: 'accent' | 'fg'; label: string }) {
  const pct = of > 0 ? Math.min(100, (value / of) * 100) : 0
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-label={label} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <span className={cn('block h-full', tone === 'accent' ? 'bg-accent' : 'bg-fg-3/60')} style={{ width: `${pct}%` }} />
    </div>
  )
}

function SlotView({ slot }: { slot: Slot }) {
  const reading = slot.processing && slot.decoded === 0 && slot.prompt_done < slot.prompt_tokens
  if (!slot.processing) {
    return <p className="text-[11.5px] text-fg-3">Idle{slot.in_context > 0 && ` · the last request filled ${count(slot.in_context)} of ${tokens(slot.context)} tokens`}</p>
  }
  return (
    <div className="grid gap-1.5">
      <p className="flex flex-wrap gap-x-3 text-[12px] text-fg-2">
        {reading
          ? <span className="text-accent">Reading the prompt · {count(slot.prompt_done)} of {count(slot.prompt_tokens)} tokens</span>
          : <span className="text-accent">Writing · {count(slot.decoded)} tokens{slot.tps != null && ` · ${slot.tps} tok/s`}</span>}
        {slot.prompt_cached > 0 && <span className="text-fg-3">{count(slot.prompt_cached)} prompt tokens reused from the cache</span>}
      </p>
      {reading && <Bar value={slot.prompt_done} of={slot.prompt_tokens} label="Prompt read" />}
      <div className="grid gap-0.5">
        <Bar value={slot.in_context} of={slot.context} tone="fg" label="Context in use" />
        <p className="text-[11px] text-fg-3">{count(slot.in_context)} of {count(slot.context)} context tokens in use</p>
      </div>
    </div>
  )
}

function LoadedNow({ servers }: { servers: ActivityServer[] }) {
  return (
    <div className="grid content-start gap-3">
      <h3 className="text-[12px] font-medium text-fg-2">Loaded now</h3>
      {servers.map((s) => (
        <div key={s.server} className="grid gap-2">
          <p className="text-[11.5px] text-fg-3">{s.server === 'gpu' ? 'GPU router' : 'CPU router'}</p>
          {s.models.length === 0
            ? <p className="text-[12px] text-fg-3">Nothing loaded</p>
            : s.models.map((m) => (
              <div key={m.preset} className="grid gap-2 rounded-lg border border-line/60 bg-surface-2/40 p-2.5">
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
                  <span className="font-mono text-fg">{m.model}</span>
                  {m.context && <Chip>{tokens(m.context)} context</Chip>}
                  {m.vision && <Chip>images</Chip>}
                  {m.device && <Chip>{deviceText({ device: m.device, gpu_layers: m.gpu_layers ?? 0, layers: m.layers ?? 0 })}</Chip>}
                  {m.status === 'loading' && <Chip tone="accent">loading</Chip>}
                  <span className="ml-auto font-mono text-[11px] text-fg-3">
                    {[m.vram_mb ? `${megabytes(m.vram_mb)} VRAM` : null, m.ram_mb ? `${megabytes(m.ram_mb)} RAM` : null].filter(Boolean).join(' · ')}
                  </span>
                </p>
                {m.slots.map((slot) => <SlotView key={slot.id} slot={slot} />)}
              </div>
            ))}
        </div>
      ))}
    </div>
  )
}

function RunningNow({ data }: { data: Activity }) {
  const holder = data.lane.holder
  return (
    <div className="grid content-start gap-3">
      <h3 className="text-[12px] font-medium text-fg-2">Running now</h3>
      {data.calls.length === 0 ? <p className="text-[12px] text-fg-3">No model calls running.</p> : (
        <ul className="grid gap-1.5">
          {data.calls.map((c) => (
            <li key={c.id} className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
              <span className="text-fg">{c.label}</span>
              <span className="font-mono text-[11.5px] text-fg-3">{c.model}</span>
              <span className="text-[11.5px] text-fg-3">{requester(c)}</span>
              {c.swapped && <Chip tone="warn">swapped in</Chip>}
              <span className="ml-auto font-mono text-[11.5px] text-fg-2">{duration(c.elapsed ?? 0)}</span>
            </li>
          ))}
        </ul>
      )}
      {holder && <p className="text-[12px] text-fg-3">{HOLDERS[holder] ?? `Loading ${holder} for a chat: background work waits.`}</p>}
      <h3 className="mt-1 text-[12px] font-medium text-fg-2">Waiting</h3>
      <Waiting data={data} />
    </div>
  )
}

function Waiting({ data }: { data: Activity }) {
  const queued = data.queues.filter((q) => q.count > 0)
  if (data.lane.waiting.length === 0 && queued.length === 0) return <p className="text-[12px] text-fg-3">Nothing waiting.</p>
  return (
    <div className="grid gap-1.5 text-[12.5px]">
      {data.lane.waiting.map((w, i) => (
        <p key={i} className="flex flex-wrap gap-x-2">
          <span className="text-fg">{w.label}</span>
          <span className="text-fg-3">{w.reason === 'paused' ? 'held by the pause' : 'waits for a chat'}, {ago(data.now, w.since).replace(' ago', '')}</span>
        </p>
      ))}
      {queued.length > 0 && (
        <p className="flex flex-wrap gap-1.5">
          {queued.map((q) => <Chip key={q.label}>{q.label} <span className="font-mono">{count(q.count)}</span></Chip>)}
          <span className="text-[11.5px] text-fg-3">in the queue</span>
        </p>
      )}
    </div>
  )
}

type Tab = 'recent' | 'swaps' | 'today'
const TABS: { value: Tab; label: string }[] = [
  { value: 'recent', label: 'Recent calls' }, { value: 'swaps', label: 'Model swaps' }, { value: 'today', label: 'Today by feature' },
]

const th = 'py-1 pr-3 font-normal'
const STATUS_TONE = { done: 'text-good', failed: 'text-bad', stopped: 'text-fg-3' } as const

const PAGE_ROWS = 20

function Recent({ rows, now }: { rows: ModelCall[]; now: number }) {
  if (rows.length === 0) return <p className="text-[12px] text-fg-3">No model calls yet.</p>
  return (
    <table className="w-full min-w-[640px] text-[12px]">
      <thead className="text-left text-[11px] text-fg-3">
        <tr><th className={th}>When</th><th className={th}>Feature</th><th className={th}>Model</th><th className={th}>Requested by</th>
          <th className={th}>Tokens in → out</th><th className={th}>Time</th><th className={th}>Speed</th><th className="py-1 font-normal">Result</th></tr>
      </thead>
      <tbody className="text-fg-2">
        {rows.map((c) => {
          const tps = c.kind === 'chat' && c.output_tokens && c.seconds ? c.output_tokens / c.seconds : null
          return (
            <tr key={c.id} className="border-t border-line/60">
              <td className="py-1 pr-3 text-fg-3">{ago(now, c.started + (c.seconds ?? 0))}</td>
              <td className="py-1 pr-3 text-fg">{c.label}</td>
              <td className="py-1 pr-3 font-mono">{c.model}{c.swapped && <span className="ml-1.5 font-sans text-[11px] text-warn" title="Its router loaded this model first">swap</span>}</td>
              <td className="py-1 pr-3">{requester(c)}</td>
              <td className="py-1 pr-3 font-mono">{count(c.input_tokens)}{c.kind === 'chat' && ` → ${count(c.output_tokens)}`}</td>
              <td className="py-1 pr-3 font-mono">{seconds(c.seconds ?? 0)}</td>
              <td className="py-1 pr-3 font-mono" title="Answer tokens over the whole call, loading and reading the prompt included">{tps ? `${tps.toFixed(1)} tok/s` : '—'}</td>
              <td className={cn('py-1', STATUS_TONE[c.status ?? 'done'])} title={c.error ?? undefined}>{c.status === 'failed' ? `failed${c.error ? ` · ${c.error}` : ''}` : c.status}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function Swaps({ rows, now }: { rows: Swap[]; now: number }) {
  if (rows.length === 0) return <p className="text-[12px] text-fg-3">No swaps yet.</p>
  return (
    <table className="w-full min-w-[560px] text-[12px]">
      <thead className="text-left text-[11px] text-fg-3">
        <tr><th className={th}>When</th><th className={th}>Router</th><th className={th}>Change</th><th className={th}>Because of</th><th className="py-1 font-normal">Load</th></tr>
      </thead>
      <tbody className="text-fg-2">
        {rows.map((s, i) => (
          <tr key={i} className="border-t border-line/60">
            <td className="py-1 pr-3 text-fg-3">{ago(now, s.at)}</td>
            <td className="py-1 pr-3">{s.server === 'gpu' ? 'GPU' : 'CPU'}</td>
            <td className="py-1 pr-3 font-mono">
              {s.after === null ? <>{s.before} <span className="font-sans text-fg-3">unloaded</span></>
                : s.before ? <>{s.before} <span className="text-fg-3">→</span> {s.after}</> : <><span className="font-sans text-fg-3">loaded</span> {s.after}</>}
            </td>
            <td className="py-1 pr-3">{s.cause_label}</td>
            <td className="py-1 font-mono">{s.seconds != null ? seconds(s.seconds) : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Today({ rows }: { rows: FeatureToday[] }) {
  if (rows.length === 0) return <p className="text-[12px] text-fg-3">No model calls today.</p>
  return (
    <table className="w-full min-w-[520px] text-[12px]">
      <thead className="text-left text-[11px] text-fg-3">
        <tr><th className={th}>Feature</th><th className={th}>Calls</th><th className={th}>Failed</th><th className={th}>Tokens in</th>
          <th className={th}>Tokens out</th><th className="py-1 font-normal">Time on the model</th></tr>
      </thead>
      <tbody className="font-mono text-fg-2">
        {rows.map((f) => (
          <tr key={f.feature} className="border-t border-line/60">
            <td className="py-1 pr-3 font-sans text-fg">{f.label}</td>
            <td className="py-1 pr-3">{count(f.calls)}</td>
            <td className={cn('py-1 pr-3', f.failed > 0 && 'text-bad')}>{count(f.failed)}</td>
            <td className="py-1 pr-3">{count(f.input_tokens)}</td>
            <td className="py-1 pr-3">{count(f.output_tokens)}</td>
            <td className="py-1">{duration(f.seconds)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * What the model servers are doing: what is loaded and how far each request has got, which feature is calling,
 * what waits, and what ran lately. No prompt or answer text is shown. Settings → Models and keys.
 */
export function ModelActivityCard() {
  const activity = useModelActivity()
  const [tab, setTab] = useState<Tab>('recent')
  const [page, setPage] = useState(1)
  const data = activity.data
  if (activity.isLoading) return <Card className="p-4"><Spinner label="Reading what the models are doing…" /></Card>
  if (!data) return <Notice tone="error" title="Model activity could not be read">{apiErrorMessage(activity.error, 'Try again in a moment.')}</Notice>
  const rows = tab === 'recent' ? data.recent : tab === 'swaps' ? data.swaps : data.today
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_ROWS))
  const shown = Math.min(page, pages)  // the lists are capped, so a page can run out as old rows drop off
  const from = (shown - 1) * PAGE_ROWS
  return (
    <Card className="grid gap-0 overflow-hidden">
      <div className="border-b border-line p-4"><PauseControl data={data} /></div>
      <div className="grid gap-6 border-b border-line p-4 md:grid-cols-2">
        <LoadedNow servers={data.servers} />
        <RunningNow data={data} />
      </div>
      <div className="grid gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="What to show" value={tab} options={TABS} onChange={(next) => { setTab(next); setPage(1) }} />
          <Pager page={shown} pages={pages} onChange={setPage} label="Pages" className="ml-auto" />
        </div>
        <div className="overflow-x-auto">
          {tab === 'recent' ? <Recent rows={data.recent.slice(from, from + PAGE_ROWS)} now={data.now} />
            : tab === 'swaps' ? <Swaps rows={data.swaps.slice(from, from + PAGE_ROWS)} now={data.now} />
              : <Today rows={data.today.slice(from, from + PAGE_ROWS)} />}
        </div>
        {pages > 1 && (
          <p className="text-[11.5px] text-fg-3">{from + 1}–{Math.min(from + PAGE_ROWS, rows.length)} of {rows.length}</p>
        )}
      </div>
    </Card>
  )
}
