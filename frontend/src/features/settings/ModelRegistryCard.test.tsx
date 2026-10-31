import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Inspection, Registry, RegistryContext, RegistryModel } from '../../api/queries/modelRegistry'
import { mockApi, renderWithProviders } from '../../test/utils'
import { ModelRegistryCard } from './ModelRegistryCard'

const ctx = (tokens: number, device: RegistryContext['device'], tps: number, status: string | null = null): RegistryContext => ({
  tokens, preset: `qwen3.5-9b@${tokens / 1024}k`, vision_preset: null, server: device === 'cpu' ? 'cpu' : 'gpu', device,
  gpu_layers: device === 'gpu' ? 33 : device === 'split' ? 27 : 0, layers: 33, vram_mb: device === 'cpu' ? 0 : 6052, ram_mb: device === 'gpu' ? 0 : 984,
  fits: true, measured: true, tps, prompt_tps: 900, speed_source: 'measured', load_seconds: 5.2, samples: 3, status,
})

const REGISTRY: Registry = {
  models: [{
    id: 'm1', name: 'qwen3.5-9b', path: '/models/Qwen3.5-9B-Q4_K_M.gguf', mmproj_path: '/models/mmproj-F16.gguf', size_bytes: 5_680_000_000,
    mmproj_bytes: 918_000_000, info: { architecture: 'qwen35', params: '9B', quant: 'Q4_K_M' }, role: 'chat', reasoning: true, tools: true,
    vision: true, placement: 'auto', default_context: 20480, enabled: true, layers: 33,
    contexts: [ctx(20480, 'gpu', 38.2, 'loaded'), ctx(65536, 'split', 14)], exists: true, changed: false,
    used_for: ['default chat model'], benchmarked: true, complete: true, needed_bytes: 5_680_000_000, is_default: true,
    loaded: true, last_benchmark: null, context_steps: [8192, 16384, 20480, 32768, 65536, 131072, 262144],
  }, {
    id: 'm2', name: 'qwen3.8-27b', path: '/models/Qwen3.8-27B-q4_k_m.gguf', mmproj_path: null, size_bytes: 10_544_480_256,
    mmproj_bytes: null, info: { architecture: 'qwen35', params: '27B', quant: 'Q4_K_M' }, role: 'chat', reasoning: true, tools: true,
    vision: false, placement: 'auto', default_context: 16384, enabled: true, layers: 65, contexts: [ctx(16384, 'cpu', 2)], exists: true,
    changed: false, used_for: [], benchmarked: false, complete: false, needed_bytes: 17_457_944_384, is_default: false, loaded: false,
    last_benchmark: null, context_steps: [16384],
  }, {
    id: 'm3', name: 'qwen3-embedding-8b', path: '/models/Qwen3-Embedding-8B-Q4_K_M.gguf', mmproj_path: null, size_bytes: 4_680_000_000,
    mmproj_bytes: null, info: { architecture: 'qwen3', params: '8B', quant: 'Q4_K_M' }, role: 'embed', reasoning: false, tools: false,
    vision: false, placement: 'auto', default_context: 2048, enabled: true, layers: 37,
    contexts: [{ ...ctx(2048, 'gpu', 0, 'unloaded'), preset: 'qwen3-embedding-8b', tps: null, prompt_tps: 2410 }], exists: true,
    changed: false, used_for: ['embeddings'], benchmarked: true, complete: true, needed_bytes: null, is_default: true, loaded: false,
    last_benchmark: null, context_steps: [2048],
  }],
  gpu: { name: 'NVIDIA GeForce RTX 4060 Laptop GPU', total_mb: 8188, used_mb: 6616, llama_mb: 5788, others_mb: 828, available_mb: 6336 },
  servers: {
    gpu: { url: 'http://127.0.0.1:8080/v1', online: true, serves_registry: false, missing: ['qwen3.5-9b@64k'], loaded: ['qwen3.5-9b'] },
    cpu: { url: 'http://127.0.0.1:8081/v1', online: false, serves_registry: true, missing: [], loaded: [] },
  },
  benchmark: null, reembed: null, writable: true, read_only_reason: null, fit_tool: true, roots: ['/models'], margin_mb: 1024,
}

const SEEN: Inspection = {
  info: { kind: 'model', path: '/models/gemma-3-4b-Q4_K_M.gguf', filename: 'gemma-3-4b-Q4_K_M.gguf', size_bytes: 2_500_000_000, name: 'Gemma 3 4B',
    architecture: 'gemma3', params: '4B', quant: 'Q4_K_M', layers: 34, context_train: 131072, role: 'chat', thinks: false, tools: true },
  name: 'gemma-3-4b', contexts: [8192, 16384, 32768, 65536], default_context: 16384,
  projectors: [{ kind: 'mmproj', path: '/models/mmproj-gemma.gguf', filename: 'mmproj-gemma.gguf', size_bytes: 800_000_000, name: 'Gemma 3 4B', match: true }],
  reasoning: false, tools: true, already: false,
  preview: [8192, 16384, 32768, 65536].map((tokens) => ({ tokens, device: 'gpu' as const, gpu_layers: 35, layers: 35, vram_mb: 3000, ram_mb: 0, fits: true })),
}

describe('the model registry', () => {
  it('shows the GPU, the routers and each context with its device and speed', async () => {
    mockApi({ 'GET /models': { data: REGISTRY } })
    renderWithProviders(<ModelRegistryCard />)
    expect(await screen.findByText('NVIDIA GeForce RTX 4060 Laptop GPU')).toBeInTheDocument()
    expect(screen.getByText(/running from the old preset file/)).toBeInTheDocument()
    const rows = screen.getAllByRole('row')
    expect(rows[1]).toHaveTextContent(/20k.*default.*GPU.*5\.9 GB.*38 tok\/s.*5\.2 s.*loaded/)
    expect(rows[2]).toHaveTextContent(/64k.*GPU \+ CPU · 27\/33 layers on GPU.*14 tok\/s/)
    expect(screen.queryByText(/qwen3.8-27b/)).not.toBeInTheDocument()  // one model at a time
  })

  it('picks a model from the menu, says when its file is incomplete, and makes another the default', async () => {
    mockApi({ 'GET /models': { data: REGISTRY } })
    renderWithProviders(<ModelRegistryCard />)
    await userEvent.click(await screen.findByTitle('Pick a model to see and change'))
    await userEvent.click(screen.getByRole('radio', { name: /qwen3.8-27b.*incomplete/ }))
    expect(screen.getByText(/It holds 10\.5 GB of the 17\.5 GB its weights need/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Benchmark/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Make default/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByTitle('Pick a model to see and change'))
    await userEvent.click(screen.getByRole('radio', { name: /qwen3.5-9b/ }))
    expect(screen.getByRole('button', { name: /Unload/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Make default/ })).not.toBeInTheDocument()  // already is
  })

  it('says when background work will load an unloaded model again, and pauses it', async () => {
    const calls = mockApi({
      'GET /models': { data: REGISTRY },
      'POST /models/m1/unload': { data: { unloaded: ['qwen3.5-9b'], reloaded_by: ['Summaries', 'Cluster labels'] } },
      'POST /models/activity/pause': { data: { paused: { by: 'Ada', since: 1 } } },
    })
    renderWithProviders(<ModelRegistryCard />)
    await userEvent.click(await screen.findByRole('button', { name: /Unload/ }))
    expect(await screen.findByText('Summaries and Cluster labels will load qwen3.5-9b again')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Pause background work/ }))
    expect(await screen.findByText('Background work is paused.')).toBeInTheDocument()
    expect(calls.map((c) => `${c.method} ${c.url}`)).toContain('POST /models/activity/pause')
  })

  it('loads an unloaded model, and shows an embedder with its reading speed', async () => {
    const calls = mockApi({ 'GET /models': { data: REGISTRY }, 'POST /models/m3/load': { status: 202, data: { started: true, preset: 'qwen3-embedding-8b' } } })
    renderWithProviders(<ModelRegistryCard />)
    await userEvent.click(await screen.findByTitle('Pick a model to see and change'))
    await userEvent.click(screen.getByRole('radio', { name: /qwen3-embedding-8b/ }))
    expect(screen.getByText('default embedding model')).toBeInTheDocument()
    expect(screen.getAllByRole('row')[1]).toHaveTextContent(/2k.*2,410 tok\/s read/)
    expect(screen.getByRole('button', { name: /Re-benchmark/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Turn off/ })).toBeDisabled()  // every vector comes from it
    expect(screen.queryByRole('button', { name: /Make default/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^Load/ }))
    await waitFor(() => expect(calls.map((c) => `${c.method} ${c.url}`)).toContain('POST /models/m3/load'))
  })

  it('warns before another embedder becomes the default, and shows the re-embedding', async () => {
    const other: RegistryModel = { ...REGISTRY.models[2], id: 'm4', name: 'bge-m3', is_default: false, used_for: [] }
    const reembed = { model: 'bge-m3', previous: 'qwen3-embedding-8b', by: 'Ada', since: 1_793_000_000, feed_left: 1200,
      maps_left: 30, projects_left: 0, done: false }
    let registry: Registry = { ...REGISTRY, models: [...REGISTRY.models, other] }
    const calls = mockApi({
      'GET /models': () => ({ data: registry }),
      'POST /models/m4/default': () => { registry = { ...registry, reembed }; return { data: { ...other, is_default: true } } },
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    renderWithProviders(<ModelRegistryCard />)
    await userEvent.click(await screen.findByTitle('Pick a model to see and change'))
    await userEvent.click(screen.getByRole('radio', { name: /bge-m3/ }))
    await userEvent.click(screen.getByRole('button', { name: /Make default/ }))
    expect(confirm.mock.calls[0][0]).toMatch(/Every stored vector is thrown away/)
    expect(calls.some((c) => c.url === '/models/m4/default')).toBe(false)  // said no
    await userEvent.click(screen.getByRole('button', { name: /Make default/ }))
    expect(await screen.findByText('Embedding everything again with bge-m3')).toBeInTheDocument()
    expect(screen.getByText(/Left: 1,200 feed items, 30 map passages and abstracts\./)).toBeInTheDocument()
    confirm.mockRestore()
  })

  it('adds a model picked from a folder, with its projector and context sizes', async () => {
    const places = [{ name: 'Athena models', path: '/repo/models' }, { name: 'Home', path: '/home/me' }, { name: 'Computer', path: '/' }]
    const calls = mockApi({
      'GET /models': { data: REGISTRY },
      'GET /models/browse': (config) => (config.params?.path === '/models'
        ? { data: { path: '/models', parent: '/', places, entries: [
          { name: 'gemma-3-4b-Q4_K_M.gguf', path: '/models/gemma-3-4b-Q4_K_M.gguf', kind: 'model', size_bytes: 2_500_000_000 },
          { name: 'mmproj-gemma.gguf', path: '/models/mmproj-gemma.gguf', kind: 'mmproj', size_bytes: 800_000_000 },
        ] } }
        : config.params?.path === '/'
          ? { data: { path: '/', parent: null, places, entries: [{ name: 'models', path: '/models', kind: 'dir', size_bytes: null }] } }
          : { data: { path: '/repo/models', parent: '/repo', places, entries: [] } }),
      'POST /models/inspect': { data: SEEN },
      'POST /models': { status: 201, data: { id: 'm3' } },
    })
    renderWithProviders(<ModelRegistryCard />)
    await userEvent.click(await screen.findByRole('button', { name: /Add model/ }))
    const dialog = screen.getByRole('dialog', { name: 'Add a model' })
    expect(await within(dialog).findByText('No folders or .gguf files here.')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Computer' }))
    await userEvent.click(await within(dialog).findByRole('button', { name: /^models/ }))
    expect(await within(dialog).findByRole('button', { name: /mmproj-gemma/ })).toBeDisabled()  // a projector is not a model
    expect(within(dialog).getByRole('list', { name: 'Folder path' })).toHaveTextContent('/models')
    await userEvent.click(within(dialog).getByRole('button', { name: /gemma-3-4b-Q4_K_M/ }))
    expect(await within(dialog).findByDisplayValue('gemma-3-4b')).toBeInTheDocument()
    expect(within(dialog).getByRole('combobox', { name: /Vision projector/ })).toHaveValue('/models/mmproj-gemma.gguf')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Offer 64k' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add model' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST' && c.url === '/models')?.body).toEqual({
      path: '/models/gemma-3-4b-Q4_K_M.gguf', name: 'gemma-3-4b', role: 'chat', mmproj_path: '/models/mmproj-gemma.gguf',
      reasoning: false, tools: true, placement: 'auto', contexts: [8192, 16384, 32768], default_context: 16384,
    }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
