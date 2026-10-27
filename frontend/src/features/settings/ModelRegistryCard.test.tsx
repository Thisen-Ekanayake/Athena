import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Inspection, Registry, RegistryContext } from '../../api/queries/modelRegistry'
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
    used_for: ['default chat model'], benchmarked: true,
  }],
  gpu: { name: 'NVIDIA GeForce RTX 4060 Laptop GPU', total_mb: 8188, used_mb: 6616, llama_mb: 5788, others_mb: 828, available_mb: 6336 },
  servers: {
    gpu: { url: 'http://127.0.0.1:8080/v1', online: true, serves_registry: false, missing: ['qwen3.5-9b@64k'], loaded: ['qwen3.5-9b'] },
    cpu: { url: 'http://127.0.0.1:8081/v1', online: false, serves_registry: true, missing: [], loaded: [] },
  },
  benchmark: null, writable: true, read_only_reason: null, fit_tool: true, roots: ['/models'], margin_mb: 1024,
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
    // In use by background work: it cannot be removed or turned off
    expect(screen.getByRole('button', { name: 'Remove qwen3.5-9b' })).toBeDisabled()
  })

  it('adds a model picked from a folder, with its projector and context sizes', async () => {
    const calls = mockApi({
      'GET /models': { data: REGISTRY },
      'GET /models/browse': { data: { path: '/models', parent: null, roots: ['/models'], entries: [
        { name: 'gemma-3-4b-Q4_K_M.gguf', path: '/models/gemma-3-4b-Q4_K_M.gguf', kind: 'model', size_bytes: 2_500_000_000 },
        { name: 'mmproj-gemma.gguf', path: '/models/mmproj-gemma.gguf', kind: 'mmproj', size_bytes: 800_000_000 },
      ] } },
      'POST /models/inspect': { data: SEEN },
      'POST /models': { status: 201, data: {} },
    })
    renderWithProviders(<ModelRegistryCard />)
    await userEvent.click(await screen.findByRole('button', { name: /Add model/ }))
    const dialog = screen.getByRole('dialog', { name: 'Add a model' })
    await userEvent.click(await within(dialog).findByRole('button', { name: /gemma-3-4b-Q4_K_M\.gguf/ }))
    expect(within(dialog).getByRole('button', { name: /mmproj-gemma/ })).toBeDisabled()  // a projector is not a model
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
