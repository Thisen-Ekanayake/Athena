import { describe, expect, it } from 'vitest'
import { apply, parseEvents, type Draft } from './chatStore'

const draft = (): Draft => ({
  question: 'Why?', attachments: [], retry: false, model: 'qwen3.5-9b', effort: 'low', content: '', reasoning: '',
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
