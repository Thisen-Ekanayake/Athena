import { Fragment, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { ArrowUp, FileText, RotateCcw } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../../api/client'
import { Oracle } from '../astrolabe/Oracle'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { useAddHighlight } from '../../api/queries/personal'
import { Highlightable } from '../reading/Highlightable'
import { PaperPanel } from './PaperPanel'
import { useClearMapQuestions, useMapQuestions, type MapSource, type SectionFilter } from './api'

const FILTERS: { value: SectionFilter; label: string }[] = [
  { value: 'method', label: 'Methods' },
  { value: 'results', label: 'Results' },
  { value: 'limitations', label: 'Limitations' },
]

const SECTION_LABELS: Record<string, string> = {
  abstract: 'Abstract', intro: 'Introduction', related_work: 'Related work', method: 'Method', results: 'Results',
  discussion: 'Discussion', limitations: 'Limitations', conclusion: 'Conclusion', future_work: 'Future work', other: 'Body',
}

interface Turn {
  id: string
  question: string
  answer: string
  sources: MapSource[]
  pending?: boolean
  error?: string
}

/** Questions answered from this map's papers, each claim citing a paper and section. */
export function AskMap({ slug, topicName }: { slug: string; topicName: string }) {
  const queryClient = useQueryClient()
  const saved = useMapQuestions(slug)
  const clear = useClearMapQuestions(slug)
  const [input, setInput] = useState('')
  const [sections, setSections] = useState<SectionFilter[]>([])
  const [pending, setPending] = useState<Turn | null>(null)
  const [limit, setLimit] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const turns: Turn[] = [...(saved.data ?? []), ...(pending ? [pending] : [])]
  const streaming = !!pending?.pending

  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [pending?.answer, saved.data?.length])

  const send = async (question: string) => {
    if (!question || streaming) return
    setLimit(null)
    const history = (saved.data ?? []).slice(-3).map((t) => ({ question: t.question, answer: t.answer }))
    let turn: Turn = { id: 'pending', question, answer: '', sources: [], pending: true }
    setPending(turn)
    const update = (patch: Partial<Turn>) => {
      turn = { ...turn, ...patch }
      setPending(turn)
    }
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const res = await fetch(`${API_BASE}/evolution/topics/${slug}/ask`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, sections, history }),
        signal: controller.signal,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        if (res.status === 429) setLimit(body.detail ?? 'You have reached today’s allowance.')
        throw new Error(body.detail || 'The question could not be answered.')
      }
      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (reader) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ') || line === 'data: [DONE]') continue
          let event: { sources?: MapSource[]; token?: string; error?: string; done?: boolean }
          try {
            event = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          if (event.sources) update({ sources: event.sources })
          if (event.token) update({ answer: turn.answer + event.token })
          if (event.error) update({ error: event.error })
        }
      }
      await queryClient.invalidateQueries({ queryKey: ['evolution', 'questions', slug] })
      setPending(turn.error ? { ...turn, pending: false } : null)
    } catch (e) {
      if (controller.signal.aborted) return
      update({ pending: false, error: e instanceof Error ? e.message : 'The answer stopped early.' })
    }
  }

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    const q = input.trim()
    if (!q) return
    setInput('')
    void send(q)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const toggle = (f: SectionFilter) => setSections((s) => (s.includes(f) ? s.filter((x) => x !== f) : [...s, f]))

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="relative grid min-w-0 rounded-xl border border-line bg-surface">
        <span className="ai-ring" data-active={streaming} aria-hidden="true" />
        <header className="flex flex-wrap items-center gap-3 px-4 pt-3.5">
          <Oracle mode={streaming ? 'thinking' : turns.length ? 'done' : 'idle'} size={44} />
          <div className="min-w-0 flex-1">
            <p className="text-[13.5px] font-medium text-fg">Ask {topicName}</p>
            <p className="text-[12px] text-fg-3">
              Answers come from this map’s papers: passages from those with open full text, abstracts for the rest. Click a [number] to see the paper.
            </p>
          </div>
          {(saved.data?.length ?? 0) > 0 && !streaming && (
            <Button variant="ghost" size="icon-sm" onClick={() => clear.mutate()} title="Clear these questions" aria-label="Clear these questions">
              <RotateCcw />
            </Button>
          )}
        </header>

        <div className="grid max-h-[620px] gap-5 overflow-y-auto px-4 pt-4">
          {saved.isLoading && <Spinner label="Loading your questions…" />}
          {!saved.isLoading && turns.length === 0 && (
            <p className="text-[13px] text-fg-3">Try: “What limits current methods?”, “How do the main approaches differ?”, or “Which datasets are used to evaluate them?”</p>
          )}
          {turns.map((t) => (
            <TurnView key={t.id} slug={slug} turn={t} selected={selected} onCite={setSelected} />
          ))}
          <div ref={endRef} />
        </div>

        {limit && <Notice tone="warn" className="mx-4 mt-3">{limit}</Notice>}

        <form onSubmit={submit} className="grid gap-2 p-4">
          <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3" role="group" aria-label="Look only in these sections">
            Look in
            <button type="button" onClick={() => setSections([])} aria-pressed={sections.length === 0} className={chipClass(sections.length === 0)}>All sections</button>
            {FILTERS.map((f) => (
              <button key={f.value} type="button" onClick={() => toggle(f.value)} aria-pressed={sections.includes(f.value)} className={chipClass(sections.includes(f.value))}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="flex items-end gap-2">
            <textarea
              id={`ask-map-${slug}`}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              maxLength={1000}
              disabled={streaming}
              placeholder={turns.length ? 'Ask a follow-up' : 'What are the open problems in this field?'}
              aria-label="Your question"
              className="max-h-28 min-h-8 flex-1 resize-none rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-[13.5px] text-fg [field-sizing:content] placeholder:text-fg-3 focus:border-accent-line focus:outline-none disabled:opacity-60"
            />
            <Button type="submit" variant="primary" size="icon" disabled={!input.trim() || streaming} aria-label="Ask">
              <ArrowUp />
            </Button>
          </div>
        </form>
      </div>

      {selected ? (
        <PaperPanel slug={slug} paperId={selected} onSelect={setSelected} onClose={() => setSelected(null)} />
      ) : (
        <aside className="rounded-xl border border-line bg-surface p-4 text-[13px] text-fg-2">
          Each claim cites its source as [number]. Click one to read the paper here, with what it built on and the gaps it states.
        </aside>
      )}
    </div>
  )
}

const chipClass = (on: boolean) =>
  cn('h-6 rounded-full border px-2.5 text-[12px] transition-colors', on ? 'border-accent-line bg-accent-soft text-fg' : 'border-line text-fg-2 hover:text-fg')

function TurnView({ slug, turn, selected, onCite }: { slug: string; turn: Turn; selected: string | null; onCite: (paperId: string) => void }) {
  const [showSources, setShowSources] = useState(false)
  const byNumber = new Map(turn.sources.map((s) => [s.n, s]))
  const abstractOnly = turn.sources.filter((s) => s.abstract_only).length
  return (
    <div className="grid gap-2">
      <p className="ml-8 justify-self-end rounded-lg bg-surface-2 px-3 py-2 text-[13.5px] text-fg">{turn.question}</p>
      {turn.pending && !turn.answer && (
        <p className="text-[12.5px] text-fg-3">
          <Spinner className="mr-1.5 inline h-3 w-3" />
          {turn.sources.length ? `Reading ${turn.sources.length} passages…` : 'Finding passages…'}
        </p>
      )}
      {turn.answer && (
        <div className="grid gap-1.5 text-[13.5px] leading-relaxed text-fg-2">
          <Answer text={turn.answer} sources={byNumber} selected={selected} onCite={onCite} />
          {turn.pending && <span className="caret" aria-hidden="true" />}
        </div>
      )}
      {turn.error && <p className="text-[12.5px] text-bad">{turn.error}</p>}
      {turn.sources.length > 0 && !turn.pending && (
        <div className="grid gap-1.5">
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-3">
            <button type="button" onClick={() => setShowSources((v) => !v)} aria-expanded={showSources} className="inline-flex items-center gap-1 hover:text-fg">
              <FileText className="h-3.5 w-3.5" aria-hidden="true" /> {turn.sources.length} sources
            </button>
            {abstractOnly > 0 && (
              <span title="These papers have no open full text, so only their abstract was read">
                · {abstractOnly} {abstractOnly === 1 ? 'is an abstract' : 'are abstracts'} only
              </span>
            )}
          </div>
          {showSources && (
            <ol className="grid gap-1">
              {turn.sources.map((s) => <SourceEntry key={s.n} slug={slug} source={s} onCite={onCite} />)}
            </ol>
          )}
        </div>
      )}
    </div>
  )
}

/** One cited passage: its paper, its section, and the passage itself, which you can highlight onto the paper. */
function SourceEntry({ slug, source: s, onCite }: { slug: string; source: MapSource; onCite: (paperId: string) => void }) {
  const [open, setOpen] = useState(false)
  const addHighlight = useAddHighlight('paper', s.paper_id)
  const section = s.abstract_only ? 'abstract only' : SECTION_LABELS[s.section_type] ?? s.section_type
  return (
    <li className="grid gap-1 text-[12.5px]">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-fg-3 tabular-nums">[{s.n}]</span>
        <button type="button" onClick={() => onCite(s.paper_id)} className="min-w-0 text-left text-fg-2 hover:text-fg hover:underline">
          {s.named_method ?? s.title} ({s.year ?? 'n.d.'})
        </button>
        <span className="shrink-0 text-fg-3">{section}</span>
        {s.excerpt && (
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="ml-auto shrink-0 text-fg-3 hover:text-fg">
            {open ? 'Hide passage' : 'Passage'}
          </button>
        )}
      </div>
      {open && s.excerpt && (
        <Highlightable
          text={s.excerpt}
          field="passage"
          context={{ topic: slug, section: s.abstract_only ? 'abstract' : s.section_type, heading: s.heading }}
          onHighlight={(h) => addHighlight.mutateAsync(h)}
          className="ml-7 rounded-lg bg-surface-2 px-3 py-2 leading-relaxed text-fg-2"
        />
      )}
      {addHighlight.isSuccess && open && <p className="ml-7 text-[11.5px] text-fg-3">Saved to your notes on this paper.</p>}
    </li>
  )
}

const CITATION = /\[(\d+(?:\s*[,–-]\s*\d+)*)\]/g

/** The answer with [n] citations as buttons, **bold** and simple bullet lists. */
function Answer({ text, sources, selected, onCite }: { text: string; sources: Map<number, MapSource>; selected: string | null; onCite: (paperId: string) => void }) {
  const inline = (line: string, key: string): ReactNode[] => {
    const out: ReactNode[] = []
    let last = 0
    for (const m of line.matchAll(CITATION)) {
      out.push(...bold(line.slice(last, m.index), `${key}-t${last}`))
      const numbers = m[1].split(/\s*,\s*/).map(Number)
      out.push(
        <span key={`${key}-c${m.index}`} className="whitespace-nowrap">
          {numbers.map((n) => {
            const s = sources.get(n)
            if (!s) return <span key={n} className="font-mono text-[11.5px] text-fg-3">[{n}]</span>
            return (
              <button
                key={n}
                type="button"
                onClick={() => onCite(s.paper_id)}
                title={`${s.title} (${s.year ?? 'n.d.'}) · ${s.abstract_only ? 'abstract only' : `${SECTION_LABELS[s.section_type] ?? s.section_type}: ${s.heading}`}`}
                className={cn('mx-px rounded px-1 font-mono text-[11.5px] align-baseline transition-colors', selected === s.paper_id ? 'bg-accent text-on-primary' : 'bg-accent-soft text-accent-ink hover:bg-accent hover:text-on-primary')}
              >
                {n}
              </button>
            )
          })}
        </span>,
      )
      last = (m.index ?? 0) + m[0].length
    }
    out.push(...bold(line.slice(last), `${key}-end`))
    return out
  }
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, i) => {
        const bullet = /^\s*[*-]\s+/.exec(line)
        if (!line.trim()) return <Fragment key={i} />
        return bullet ? (
          <p key={i} className="flex gap-2 pl-1"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden="true" /><span>{inline(line.slice(bullet[0].length), `l${i}`)}</span></p>
        ) : (
          <p key={i}>{inline(line, `l${i}`)}</p>
        )
      })}
    </>
  )
}

function bold(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={`${key}-${i}`} className="font-medium text-fg">{part.slice(2, -2)}</strong> : part,
  )
}
