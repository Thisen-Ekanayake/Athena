import type { ReactNode } from 'react'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Chat, ChatMap, ChatMessage, ChatModels, MapDigest } from '../api/queries/chats'
import type { EvolutionNode, EvolutionTopic } from '../features/evolution/api'
import { mockApi, renderWithProviders } from '../test/utils'
import { ChatPage } from './ChatPage'

// The lineage map draws with WebGL, which jsdom lacks; the panel around it is under test.
vi.mock('../features/evolution/EvolutionGraph', () => ({
  EvolutionGraph: ({ nodes, actions }: { nodes: EvolutionNode[]; actions?: ReactNode }) => <div data-testid="graph">{nodes.length} papers{actions}</div>,
}))

const MODELS: ChatModels = {
  models: [
    { id: 'qwen3.5-9b', reasoning: true, vision: false, tools: true, context: 20480, loaded: true },
    { id: 'gemma-4b', reasoning: false, vision: true, tools: true, context: 8192, loaded: false },
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
  id: 'c1', title: 'LoRA questions', project_id: 'p1', project_name: 'Thesis', model: 'qwen3.5-9b', effort: 'medium', pinned: false, archived: false,
  created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:01:00Z', files: [], maps: [],
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
    expect(screen.queryByRole('term')).not.toBeInTheDocument()  // the details stay folded until asked for
    await userEvent.click(screen.getByRole('button', { name: 'Show details' }))
    const details = screen.getByLabelText('How this answer ran')
    expect(details).toHaveTextContent(/Model\s*qwen3.5-9b/)
    expect(details).toHaveTextContent(/Effort\s*medium/)
  })

  it('shows how full the context is beside the send button', async () => {
    const answered = { ...CHAT, messages: [CHAT.messages[0], { ...CHAT.messages[1], stats: { context_used: 5120, context: 20480 } }] }
    mockApi({ 'GET /chats/c1': { data: answered }, 'GET /chat/models': { data: MODELS }, 'GET /projects': { data: { projects: [] } } })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    expect(await screen.findByRole('button', { name: '5,120 / 20,480 tokens of context used (25%)' })).toBeInTheDocument()
    expect(screen.getByRole('tooltip')).toHaveTextContent('5,120 / 20,480 tokens')
    // No title bar: the chat starts with its first message; its menu stays
    expect(screen.queryByRole('heading', { name: 'LoRA questions' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Chat actions' })).toBeInTheDocument()
  })

  it('offers an effort only for a model that thinks', async () => {
    mockApi({ 'GET /chats/c1': { data: CHAT }, 'GET /chat/models': { data: MODELS }, 'GET /projects': { data: { projects: [] } } })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    const picker = await screen.findByTitle('Model, context and effort')
    await waitFor(() => expect(picker).toHaveTextContent('qwen3.5-9b· Medium'))  // once the models are in
    await userEvent.click(picker)
    const dialog = screen.getByRole('dialog', { name: 'Model, context and effort' })
    await userEvent.click(within(dialog).getByRole('button', { name: /Effort/ }))
    await userEvent.click(within(screen.getByRole('radiogroup', { name: 'Effort' })).getByRole('radio', { name: /High/ }))
    expect(screen.getByTitle('Model, context and effort')).toHaveTextContent('· High')  // picked, and the menu closed
    expect(screen.queryByRole('radiogroup', { name: 'Effort' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByTitle('Model, context and effort'))
    await userEvent.click(screen.getByRole('radio', { name: /gemma-4b/ }))
    expect(screen.getByTitle('Model, context and effort')).toHaveTextContent('gemma-4b')
    await userEvent.click(screen.getByTitle('Model, context and effort'))
    expect(within(screen.getByRole('dialog')).queryByRole('button', { name: /Effort/ })).not.toBeInTheDocument()
  })

  const context = (tokens: number, device: 'gpu' | 'split' | 'cpu', tps: number, loaded = false) => ({
    tokens, device, gpu_layers: device === 'gpu' ? 33 : 20, layers: 33, vram_mb: 6000, ram_mb: 0, fits: true, tps,
    prompt_tps: null, speed_source: 'measured' as const, load_seconds: 5, server: 'gpu' as const, loaded,
  })
  const REGISTRY: ChatModels = {
    ...MODELS,
    registry: true,
    models: [
      { id: 'qwen3.5-9b', reasoning: true, vision: true, tools: true, context: 16384, loaded: true, default_context: 16384,
        loaded_context: 16384, contexts: [context(16384, 'gpu', 38, true), context(65536, 'split', 14)], params: '9B', quant: 'Q4_K_M' },
      { id: 'tiny', reasoning: false, vision: false, tools: false, context: 8192, loaded: false, default_context: 8192,
        contexts: [context(8192, 'cpu', 9)] },
    ],
  }

  it('shows each context with its device and speed, and loads a new one as soon as it is picked', async () => {
    const calls = mockApi({
      'GET /chats/c1': { data: CHAT }, 'GET /chat/models': { data: REGISTRY }, 'GET /projects': { data: { projects: [] } },
      'POST /chat/models/warm': { data: { status: 'loading' } }, 'GET /chat/models/state': { data: { status: 'loaded' } },
    })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    const picker = await screen.findByTitle('Model, context and effort')
    await waitFor(() => expect(picker).toHaveTextContent('· 16k'))
    await userEvent.click(picker)
    expect(screen.getByRole('button', { name: /Context.*16k · 38 tok\/s/ })).toBeInTheDocument()
    await userEvent.hover(screen.getByRole('button', { name: /Context/ }))
    const contexts = screen.getByRole('radiogroup', { name: 'Context size' })
    expect(within(contexts).getByRole('radio', { name: /16k.*GPU.*loaded.*38 tok\/s/ })).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(within(contexts).getByRole('radio', { name: /64k.*GPU \+ CPU 20\/33.*reloads in ~5\.0 s.*14 tok\/s/ }))
    expect(picker).toHaveTextContent('· 64k')
    await waitFor(() => expect(calls.find((c) => c.method === 'POST' && c.url === '/chat/models/warm')?.body)
      .toEqual({ model: 'qwen3.5-9b', context: 65536 }))
  })

  it('loads the picked context when another context of the model is loaded', async () => {
    const qwen = { ...REGISTRY.models[0], loaded_context: 65536, contexts: [context(16384, 'gpu', 38), context(65536, 'split', 14, true)] }
    const calls = mockApi({
      'GET /chats/c1': { data: CHAT }, 'GET /chat/models': { data: { ...REGISTRY, models: [qwen, REGISTRY.models[1]] } },
      'GET /projects': { data: { projects: [] } },
      'POST /chat/models/warm': { data: { status: 'loading' } }, 'GET /chat/models/state': { data: { status: 'loading' } },
    })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    await waitFor(() => expect(screen.getByTitle('Model, context and effort')).toHaveTextContent('· 16k'))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST' && c.url === '/chat/models/warm').map((c) => c.body))
      .toEqual([{ model: 'qwen3.5-9b', context: 16384 }]))
  })

  it('fades out image attaching for a model that reads text only', async () => {
    mockApi({
      'GET /chats/c1': { data: { ...CHAT, model: 'tiny' } }, 'GET /chat/models': { data: REGISTRY },
      'GET /projects': { data: { projects: [] } },
    })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    await waitFor(() => expect(screen.getByTitle('Model, context and effort')).toHaveTextContent('tiny'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach images' })).toBeDisabled())  // once the models are in
    expect(screen.getByRole('button', { name: 'Attach' })).toBeEnabled()
    await userEvent.click(screen.getByTitle('Model, context and effort'))
    expect(screen.getByRole('radio', { name: /^tiny.*text only/ })).toBeInTheDocument()
    expect(screen.getByText(/tiny reads text and files only/)).toBeInTheDocument()
  })

  it('attaches research maps from the paperclip, each with or without a summary for the model', async () => {
    const attached: ChatMap = { ...PEFT_MAP, share: true }
    const calls = mockApi({
      'GET /chats/c1': { data: CHAT }, 'GET /chat/models': { data: MODELS }, 'GET /projects': { data: { projects: [] } },
      'GET /evolution/topics': { data: [TOPIC, { ...TOPIC, slug: 'diffusion', name: 'Diffusion', built_at: null, status: 'building' }] },
      'POST /chats/c1/maps': { status: 201, data: { maps: [attached] } },
      ...MAP_ROUTES,
    })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    await userEvent.click(await screen.findByRole('button', { name: 'Attach' }))
    await userEvent.click(screen.getByRole('button', { name: /Research map/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Attach research maps' })
    expect(within(dialog).queryByText('Diffusion')).not.toBeInTheDocument()  // not built: not offered
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /^PEFT/ }))
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Summary for the model' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Attach map' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ maps: [{ id: 'peft', share: true }] }))
    // one map: it opens beside the chat
    const panel = await screen.findByRole('complementary', { name: 'Research map' })
    await waitFor(() => expect(panel).toHaveTextContent('2 papers · 1 milestones'))
  })

  it('opens a map paper the answer named, and shows what the model was given', async () => {
    const chat: Chat = {
      ...CHAT, maps: [{ ...PEFT_MAP, share: true }],
      messages: [message({
        id: 'a2', content: '[A4] removed the latency of Adapters (A1). A100 GPUs help.',
        map_refs: { A4: { slug: 'peft', map: 'PEFT', paper_id: 'p4', label: 'LoRA', title: 'LoRA: Low-Rank Adaptation', authors: 'Hu et al.', year: 2021 },
          A1: { slug: 'peft', map: 'PEFT', paper_id: 'p1', label: 'Adapters', year: 2019 } },
      })],
    }
    const digest: MapDigest = {
      key: 'A', share: true, budget: 2400, level: 'compact',
      levels: { full: { text: 'Map A: PEFT (full)', tokens: 3000 }, compact: { text: 'Map A: PEFT\nA4 fixes A1', tokens: 900 }, minimal: { text: 'Map A: PEFT', tokens: 200 } },
    }
    mockApi({
      'GET /chats/c1': { data: chat }, 'GET /chat/models': { data: MODELS }, 'GET /projects': { data: { projects: [] } },
      'GET /evolution/topics': { data: [TOPIC] }, 'GET /chats/c1/maps/peft/digest': { data: digest }, ...MAP_ROUTES,
    })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    // cited by title, authors and year; an answer from before titles were kept shows the name
    const lora = (await screen.findByText('LoRA: Low-Rank Adaptation')).closest('a')!
    expect(lora).toHaveTextContent('LoRA: Low-Rank Adaptation (Hu et al., 2021)')
    expect(lora).toHaveAttribute('href', '/evolution/peft?paper=p4')
    expect(screen.getByText('Adapters').closest('a')).toHaveTextContent('Adapters (2019)')
    expect(screen.getByText(/A100/).closest('a')).toBeNull()  // not a paper the map named
    expect(screen.getByText(/removed the latency/).textContent).not.toContain('[A4]')
    await userEvent.click(lora)
    const panel = await screen.findByRole('complementary', { name: 'Research map' })
    expect(within(panel).getByRole('link', { name: /Full map/ })).toHaveAttribute('href', '/evolution/peft?paper=p4')
    expect(within(panel).getByRole('checkbox', { name: 'Summary for the model' })).toBeChecked()
    await userEvent.click(within(panel).getByRole('button', { name: /What the model sees/ }))
    expect(await within(panel).findByText(/A4 fixes A1/)).toBeInTheDocument()
    expect(within(panel).getByText(/The next turn uses/)).toHaveTextContent('compact')
  })

  it('keeps the chat’s maps and artifacts on the right edge, one click from opening', async () => {
    mockApi({
      'GET /chats/c1': { data: { ...CHAT, maps: [PEFT_MAP] } }, 'GET /chat/models': { data: MODELS }, 'GET /projects': { data: { projects: [] } },
      'GET /evolution/topics': { data: [TOPIC] }, ...MAP_ROUTES,
    })
    renderWithProviders(<ChatPage />, { route: '/chats/c1', path: '/chats/:id' })
    const rail = await screen.findByRole('navigation', { name: 'Maps and artifacts' })
    expect(within(rail).getByRole('button', { name: 'Related work' })).toBeInTheDocument()
    expect(within(rail).getByRole('button', { name: 'Attach a research map' })).toBeInTheDocument()
    await userEvent.click(within(rail).getByRole('button', { name: 'PEFT' }))
    expect(await screen.findByRole('complementary', { name: 'Research map' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Maps and artifacts' })).not.toBeInTheDocument()  // the panel holds the edge now
  })
})

const TOPIC: EvolutionTopic = {
  id: 't1', slug: 'peft', name: 'PEFT', aliases: [], description: 'Adapting large models cheaply.', status: 'ready', status_detail: null,
  built_at: '2026-10-10T00:00:00Z', origin: 'curated', query: null, build_stats: {}, paper_count: 120, milestone_count: 9,
}

const PEFT_MAP: ChatMap = {
  topic_id: 't1', slug: 'peft', name: 'PEFT', description: null, share: false, key: 'A', built: true, built_at: '2026-10-10T00:00:00Z', added_at: '',
}

const node = (id: string, milestone: boolean): EvolutionNode => ({
  id, openalex_id: `W${id}`, title: id, year: 2021, year_source: 'openalex', authors: [], author_count: 0, venue: null, cited_by_count: 1,
  kind: 'method', role: 'core', named_method: null, in_degree: 0, pagerank: 0, citation_percentile: 0, specificity: 0, on_main_path: milestone,
  milestone_score: 0, score_detail: {}, is_milestone: milestone, is_milestone_auto: milestone, milestone_override: null, override_note: null,
  full_text_status: 'parsed', url: '',
})

const MAP_ROUTES = {
  'GET /evolution/topics/peft': { data: TOPIC },
  'GET /evolution/topics/peft/graph': { data: { topic: TOPIC, nodes: [node('p1', true), node('p4', false)], edges: [], loose_edges: [], total_papers: 2, strict_links: 0, year_range: [2019, 2021] } },
}
