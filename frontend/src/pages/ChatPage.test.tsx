import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Chat, ChatMessage, ChatModels } from '../api/queries/chats'
import { mockApi, renderWithProviders } from '../test/utils'
import { ChatPage } from './ChatPage'

const MODELS: ChatModels = {
  models: [
    { id: 'qwen3.5-9b', reasoning: true, vision: false, context: 20480, loaded: true },
    { id: 'gemma-4b', reasoning: false, vision: true, context: 8192, loaded: false },
  ],
  default: 'qwen3.5-9b',
  efforts: [{ id: 'off', budget: 0 }, { id: 'low', budget: 1024 }, { id: 'medium', budget: 4096 }, { id: 'high', budget: 8192 }],
  default_effort: 'low',
  vision_model: 'qwen3.5-9b-vision',
}

const message = (m: Partial<ChatMessage>): ChatMessage => ({
  id: 'm', role: 'assistant', content: '', reasoning: null, reasoning_ms: null, steps: [], sources: [], attachments: [],
  artifacts: [], model: 'qwen3.5-9b', effort: 'medium', status: 'done', error: null, input_tokens: 0, output_tokens: 0,
  created_at: '2026-10-24T10:00:00Z', ...m,
})

const CHAT: Chat = {
  id: 'c1', title: 'LoRA questions', project_id: 'p1', project_name: 'Thesis', model: 'qwen3.5-9b', effort: 'medium',
  created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:01:00Z', files: [],
  artifacts: [{ id: 'a1', title: 'Related work', version: 2, project_id: 'p1', conversation_id: 'c1', index_status: 'indexed', created_at: '', updated_at: '', chars: 40 }],
  messages: [
    message({ id: 'u1', role: 'user', content: 'What does LoRA freeze?' }),
    message({
      id: 'a1m', content: 'It freezes the pretrained weights [1].', reasoning: 'The passage says so.', reasoning_ms: 4200,
      sources: [{ n: 1, kind: 'paper', title: 'LoRA: Low-Rank Adaptation', link: '/items/x', excerpt: 'We freeze the weights.' }],
      steps: [{ id: 's1', tool: 'search_papers', label: 'Searched for papers', args: { query: 'lora' }, status: 'done', summary: '1 papers for “lora”',
        results: [{ n: 1, title: 'DoRA', year: 2024, authors: ['S. Liu'], url: 'https://arxiv.org/abs/x', source: 'arxiv', item_id: null, meta: { title: 'DoRA' }, in_project: false }] }],
      artifacts: [{ id: 'a1', title: 'Related work', version: 2 }],
      input_tokens: 900, output_tokens: 100,
    }),
  ],
}

describe('ChatPage', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    window.scrollTo = vi.fn() as unknown as typeof window.scrollTo  // jsdom has no layout
  })

  it('shows the thinking, the tools, the sources and the artifacts of a saved answer', async () => {
    const calls = mockApi({
      'GET /chats/c1': { data: CHAT },
      'GET /chat/models': { data: MODELS },
      'GET /projects': { data: { projects: [] } },
      'POST /projects/p1/items': { status: 201, data: { id: 'i1', created: true } },
    })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    expect(await screen.findByText('What does LoRA freeze?')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Thesis' })).toHaveAttribute('href', '/projects/p1')

    await userEvent.click(screen.getByRole('button', { name: /Thought for 4 s/ }))
    expect(screen.getByText('The passage says so.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '1' }))  // the citation opens the sources
    expect(screen.getByText('LoRA: Low-Rank Adaptation')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /1 papers for/ }))
    await userEvent.click(screen.getByRole('button', { name: /Add/ }))
    expect(await screen.findByText('In project')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ kind: 'paper', meta: { title: 'DoRA' } })
    expect(screen.getByText(/qwen3.5-9b · medium effort · 1,000 tokens/)).toBeInTheDocument()
  })

  it('offers an effort only for a model that thinks', async () => {
    mockApi({ 'GET /chats/c1': { data: CHAT }, 'GET /chat/models': { data: MODELS }, 'GET /projects': { data: { projects: [] } } })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    const picker = await screen.findByTitle('Model and effort')
    await waitFor(() => expect(picker).toHaveTextContent('qwen3.5-9b· Medium'))  // once the models are in
    await userEvent.click(picker)
    const dialog = screen.getByRole('dialog', { name: 'Model and effort' })
    expect(within(dialog).getByRole('radiogroup', { name: 'Effort' })).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('radio', { name: /gemma-4b/ }))
    expect(within(dialog).queryByRole('radiogroup', { name: 'Effort' })).not.toBeInTheDocument()
    expect(screen.getByTitle('Model and effort')).toHaveTextContent('gemma-4b')
  })
})
