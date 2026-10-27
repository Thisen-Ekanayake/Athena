import { describe, expect, it } from 'vitest'
import type { LoadState } from '../api/queries/chats'
import { apply, parseEvents, type Draft } from './chatStore'

const draft = (): Draft => ({
  question: 'Why?', attachments: [], retry: false, model: 'qwen3.5-9b', effort: 'low', loading: null, content: '', reasoning: '',
  thinkingSince: null, reasoningMs: 0, steps: [], sources: [], artifacts: [], notices: [], error: null, streaming: true,
  saved: false, messageId: null,
})

describe('the chat stream', () => {
  it('splits events and keeps the unfinished tail', () => {
    const { events, rest } = parseEvents('data: {"type":"token","text":"Hi"}\n\ndata: [DONE]\n\ndata: {"type":"tok')
    expect(events).toEqual([{ type: 'token', text: 'Hi' }])
    expect(rest).toBe('data: {"type":"tok')
  })

  it('times the thinking until the answer starts', () => {
    let d = apply(draft(), { type: 'start', message_id: 'm1', model: 'qwen3.5-9b', effort: 'high' }, 0)
    d = apply(d, { type: 'reasoning', text: 'Hmm. ' }, 1000)
    d = apply(d, { type: 'reasoning', text: 'Yes.' }, 2000)
    expect(d.thinkingSince).toBe(1000)
    d = apply(d, { type: 'token', text: 'Because.' }, 4500)
    expect(d).toMatchObject({ reasoning: 'Hmm. Yes.', reasoningMs: 3500, thinkingSince: null, content: 'Because.', messageId: 'm1', effort: 'high' })
  })

  it('shows the model loading until the first words come', () => {
    const state: LoadState = {
      model: 'qwen3.5-9b', preset: 'qwen3.5-9b@32k', context: 32768, server: 'gpu', status: 'loading', progress: 0.4,
      device: { kind: 'split', gpu: 'RTX 4060', gpu_layers: 28, layers: 33, vram_mb: 6200, ram_mb: 900 },
      stages: [{ label: 'Ready', state: 'pending' }], eta_seconds: 3, expected_seconds: 6, elapsed_seconds: 3, other: null,
    }
    let d = apply(draft(), { type: 'loading', state })
    expect(d.loading?.progress).toBe(0.4)
    d = apply(d, { type: 'token', text: '' })
    expect(d.loading).not.toBeNull()  // the closing empty token is not an answer
    d = apply(d, { type: 'reasoning', text: 'Hmm.' })
    expect(d.loading).toBeNull()
  })

  it('updates a tool step in place and keeps sources and artifacts', () => {
    const running = { id: 'c1', tool: 'search_papers', label: 'Searched for papers', args: { query: 'lora' }, status: 'running' as const }
    let d = apply(draft(), { type: 'tool', step: running })
    d = apply(d, { type: 'tool', step: { ...running, status: 'done', summary: '3 papers' } })
    d = apply(d, { type: 'sources', sources: [{ n: 1, kind: 'paper', title: 'LoRA' }] })
    d = apply(d, { type: 'artifact', artifact: { id: 'a', title: 'Draft', version: 1 } })
    d = apply(d, { type: 'artifact', artifact: { id: 'a', title: 'Draft', version: 2 } })
    expect(d.steps).toHaveLength(1)
    expect(d.steps[0]).toMatchObject({ status: 'done', summary: '3 papers' })
    expect(d.sources[0].title).toBe('LoRA')
    expect(d.artifacts).toEqual([{ id: 'a', title: 'Draft', version: 2 }])
    expect(apply(d, { type: 'done', message: {} as never }).saved).toBe(true)
  })
})
