import { create } from 'zustand'
import { API_BASE } from '../api/client'
import { queryClient } from '../api/queryClient'
import type { ArtifactRef } from '../api/queries/artifacts'
import type { ChatMessage, ChatSource, Effort, ToolStep } from '../api/queries/chats'

/** What a turn being answered looks like so far. Kept outside the page, so leaving the chat does not stop it. */
export interface Draft {
  question: string
  attachments: ChatMessage['attachments']
  retry: boolean
  model: string
  effort: Effort
  content: string
  reasoning: string
  /** When the current thinking started (ms), while it streams */
  thinkingSince: number | null
  reasoningMs: number
  steps: ToolStep[]
  sources: ChatSource[]
  artifacts: ArtifactRef[]
  notices: string[]
  error: string | null
  streaming: boolean
  /** The server saved the turn (its message came back): the chat's own copy replaces this one */
  saved: boolean
  /** The assistant message the server saves this turn as (from its first event) */
  messageId: string | null
}

export interface SendBody {
  content?: string
  model: string
  effort: Effort
  attachment_ids?: string[]
  retry?: boolean
}

type Event =
  | { type: 'start'; message_id: string; model: string; effort: Effort }
  | { type: 'sources'; sources: ChatSource[] }
  | { type: 'reasoning'; text: string }
  | { type: 'token'; text: string }
  | { type: 'tool'; step: ToolStep }
  | { type: 'artifact'; artifact: ArtifactRef }
  | { type: 'notice'; text: string }
  | { type: 'done'; message: ChatMessage }
  | { type: 'title'; title: string }
  | { type: 'error'; message: string }

/** Split server-sent events out of ``buffer``; the unfinished tail comes back as ``rest``. */
export function parseEvents(buffer: string): { events: Event[]; rest: string } {
  const lines = buffer.split('\n')
  const rest = lines.pop() ?? ''
  const events: Event[] = []
  for (const line of lines) {
    if (!line.startsWith('data: ') || line === 'data: [DONE]') continue
    try {
      events.push(JSON.parse(line.slice(6)) as Event)
    } catch {
      // a broken line is skipped; the saved message is read again at the end anyway
    }
  }
  return { events, rest }
}

/** Fold one event into the draft. */
export function apply(d: Draft, e: Event, now = Date.now()): Draft {
  const stopThinking = (x: Draft) => (x.thinkingSince ? { ...x, thinkingSince: null, reasoningMs: x.reasoningMs + (now - x.thinkingSince) } : x)
  switch (e.type) {
    case 'start':
      return { ...d, model: e.model, effort: e.effort, messageId: e.message_id }
    case 'sources':
      return { ...d, sources: e.sources }
    case 'reasoning':
      return { ...d, reasoning: d.reasoning + e.text, thinkingSince: d.thinkingSince ?? now }
    case 'token':
      return { ...stopThinking(d), content: d.content + e.text }
    case 'tool': {
      const others = d.steps.filter((s) => s.id !== e.step.id)
      const at = d.steps.findIndex((s) => s.id === e.step.id)
      const steps = at === -1 ? [...others, e.step] : d.steps.map((s) => (s.id === e.step.id ? e.step : s))
      return { ...stopThinking(d), steps }
    }
    case 'artifact':
      return { ...d, artifacts: [...d.artifacts.filter((a) => a.id !== e.artifact.id), e.artifact] }
    case 'notice':
      return { ...d, notices: [...d.notices, e.text] }
    case 'error':
      return { ...stopThinking(d), error: e.message }
    case 'done':
      return { ...stopThinking(d), saved: true }
    default:
      return d
  }
}

interface ChatStreams {
  drafts: Record<string, Draft>
  send: (chatId: string, body: SendBody, shown: { question: string; attachments?: ChatMessage['attachments'] }) => Promise<void>
  stop: (chatId: string) => void
  dismiss: (chatId: string) => void
  /** The artifact open beside the chat, if any */
  artifactId: string | null
  openArtifact: (id: string | null) => void
}

const controllers = new Map<string, AbortController>()

const refresh = async (chatId: string) => {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['chat', chatId] }),
    queryClient.invalidateQueries({ queryKey: ['chats'] }),
    queryClient.invalidateQueries({ queryKey: ['project'] }),
    queryClient.invalidateQueries({ queryKey: ['projects'] }),
  ])
}

export const useChatStreams = create<ChatStreams>((set, get) => ({
  drafts: {},
  artifactId: null,
  openArtifact: (id) => set({ artifactId: id }),

  stop: (chatId) => controllers.get(chatId)?.abort(),

  dismiss: (chatId) =>
    set((s) => {
      const drafts = { ...s.drafts }
      delete drafts[chatId]
      return { drafts }
    }),

  send: async (chatId, body, shown) => {
    if (get().drafts[chatId]?.streaming) return
    const update = (fn: (d: Draft) => Draft) => set((s) => (s.drafts[chatId] ? { drafts: { ...s.drafts, [chatId]: fn(s.drafts[chatId]) } } : s))
    set((s) => ({
      drafts: {
        ...s.drafts,
        [chatId]: {
          question: shown.question, attachments: shown.attachments ?? [], retry: !!body.retry, model: body.model, effort: body.effort,
          content: '', reasoning: '', thinkingSince: null, reasoningMs: 0, steps: [], sources: [], artifacts: [], notices: [],
          error: null, streaming: true, saved: false, messageId: null,
        },
      },
    }))
    const controller = new AbortController()
    controllers.set(chatId, controller)
    try {
      const res = await fetch(`${API_BASE}/chats/${chatId}/messages`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail
        throw new Error(typeof detail === 'string' ? detail : 'The message could not be sent.')
      }
      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (reader) {
        const { value, done } = await reader.read()
        if (done) break
        const parsed = parseEvents(buffer + decoder.decode(value, { stream: true }))
        buffer = parsed.rest
        for (const event of parsed.events) {
          update((d) => apply(d, event))
          if (event.type === 'artifact' && !get().artifactId) set({ artifactId: event.artifact.id })
          if (event.type === 'title') void queryClient.invalidateQueries({ queryKey: ['chats'] })
        }
      }
    } catch (e) {
      if (!controller.signal.aborted) update((d) => ({ ...d, error: e instanceof Error ? e.message : 'The answer stopped early.' }))
    } finally {
      controllers.delete(chatId)
      update((d) => ({ ...apply(d, { type: 'token', text: '' }), streaming: false }))
      // A stopped turn is saved by the server as the request ends; give it a moment before reading it back.
      if (controller.signal.aborted) await new Promise((r) => setTimeout(r, 400))
      await refresh(chatId)
      const draft = get().drafts[chatId]
      if (draft && !draft.streaming && (draft.saved || controller.signal.aborted)) {
        set((s) => {
          const drafts = { ...s.drafts }
          delete drafts[chatId]
          return { drafts }
        })
      }
    }
  },
}))
