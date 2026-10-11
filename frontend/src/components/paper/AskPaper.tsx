import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, RotateCcw } from 'lucide-react'
import { API_BASE } from '../../api/client'
import { Oracle } from '../../features/astrolabe/Oracle'
import { useQAStore, type QAMessage } from '../../store/qaStore'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'

const EMPTY: QAMessage[] = []

type Grounding = 'full' | 'partial' | 'unavailable' | null

const GROUNDING_NOTE: Record<string, string> = {
  partial: 'Only the abstract is available, so answers are grounded in it alone.',
  unavailable: 'The article text is not available, so answers may be limited.',
}

/** A short conversation about one item, grounded in its text. The oracle wakes while an answer streams in. */
export function AskPaper({ itemId }: { itemId: string }) {
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [limitHit, setLimitHit] = useState(false)
  const [grounding, setGrounding] = useState<Grounding>(null)
  const history = useQAStore((s) => s.sessions[itemId]) ?? EMPTY
  const addMessage = useQAStore((s) => s.addMessage)
  const updateLastMessage = useQAStore((s) => s.updateLastMessage)
  const clearSession = useQAStore((s) => s.clearSession)
  const endRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const prefetched = useRef(false)

  useEffect(() => {
    let dead = false
    fetch(`${API_BASE}/items/${itemId}/qa/status`)
      .then((r) => r.json())
      .then((d: { status?: Grounding }) => {
        if (!dead) setGrounding(d.status ?? null)
      })
      .catch(() => {})
    return () => {
      dead = true
      abortRef.current?.abort()
    }
  }, [itemId])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [history])

  // Warm the server-side cache of the article text as soon as someone starts typing.
  const prefetch = () => {
    if (prefetched.current) return
    prefetched.current = true
    fetch(`${API_BASE}/items/${itemId}/qa/prefetch`).catch(() => {})
  }

  const send = async (question: string) => {
    if (!question || streaming) return
    setError(null)
    setLimitHit(false)
    const past = history
    addMessage(itemId, { role: 'user', content: question })
    addMessage(itemId, { role: 'assistant', content: '' })
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let answer = ''
    try {
      const res = await fetch(`${API_BASE}/items/${itemId}/qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, history: past }),
        signal: controller.signal,
      })
      if (!res.ok) {
        if (res.status === 429) setLimitHit(true)
        const body = await res.json().catch(() => ({}))
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
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          if (payload === '[DONE]') continue
          try {
            const { token, error: streamError } = JSON.parse(payload) as { token?: string; error?: string }
            if (streamError) throw new Error(streamError)
            if (token) {
              answer += token
              updateLastMessage(itemId, answer)
            }
          } catch (e) {
            if (e instanceof SyntaxError) continue
            throw e
          }
        }
      }
    } catch (e) {
      if (controller.signal.aborted) return
      setError(e instanceof Error ? e.message : 'The answer stopped early.')
      updateLastMessage(itemId, answer ? `${answer}\n\n(The answer stopped early.)` : '(No answer.)')
    } finally {
      setStreaming(false)
    }
  }

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    const q = input.trim()
    if (!q) return
    setInput('')
    send(q)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const mode = streaming ? 'thinking' : history.length ? 'done' : 'idle'

  return (
    <div className="relative rounded-xl border border-line bg-surface">
      <span className="ai-ring" data-active={streaming} aria-hidden="true" />
      <header className="flex items-center gap-3 px-3.5 pt-3">
        <Oracle mode={mode} size={44} />
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-medium text-fg">Ask about this paper</p>
          <p className="text-[12px] text-fg-3" aria-live="polite">
            {streaming ? <span className="font-myth text-[14px] text-fg-2">Consulting the oracle…</span> : GROUNDING_NOTE[grounding ?? ''] ?? 'Answers come from the paper itself.'}
          </p>
        </div>
        {history.length > 0 && !streaming && (
          <Button variant="ghost" size="icon-sm" onClick={() => clearSession(itemId)} title="Start over" aria-label="Clear this conversation">
            <RotateCcw />
          </Button>
        )}
      </header>

      {history.length > 0 && (
        <div className="grid max-h-[360px] gap-3 overflow-y-auto px-3.5 pt-3">
          {history.map((m, i) => (
            <div key={i} className={cn('text-[13.5px] leading-relaxed', m.role === 'user' ? 'ml-8 justify-self-end rounded-lg bg-surface-2 px-3 py-2 text-fg' : 'text-fg-2')}>
              <span className="whitespace-pre-wrap">{m.content}</span>
              {m.role === 'assistant' && streaming && i === history.length - 1 && <span className="caret" aria-hidden="true" />}
            </div>
          ))}
          <div ref={endRef} />
        </div>
      )}

      {(error || limitHit) && (
        <p className="mx-3.5 mt-3 text-[12.5px] text-bad">
          {limitHit ? 'You have asked a lot in this session. Start over to keep going.' : error}
        </p>
      )}

      <form onSubmit={submit} className="flex items-end gap-2 p-3">
        <textarea
          id={`ask-${itemId}`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onFocus={prefetch}
          onKeyDown={onKeyDown}
          rows={1}
          disabled={streaming}
          placeholder={history.length ? 'Ask a follow-up' : 'What problem does this paper solve?'}
          aria-label="Your question"
          className="max-h-28 min-h-8 flex-1 resize-none rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-[13.5px] text-fg [field-sizing:content] placeholder:text-fg-3 focus:border-accent-line focus:outline-none disabled:opacity-60"
        />
        <Button type="submit" variant="primary" size="icon" disabled={!input.trim() || streaming} aria-label="Ask">
          <ArrowUp />
        </Button>
      </form>
    </div>
  )
}
