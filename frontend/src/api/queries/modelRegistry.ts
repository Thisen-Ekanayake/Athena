import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { Device } from './chats'

/** What a GGUF header says about a model */
export interface GgufInfo {
  kind: 'model' | 'mmproj'
  path: string
  filename: string
  size_bytes: number
  name: string | null
  architecture?: string
  params?: string | null
  quant?: string | null
  layers?: number | null
  context_train?: number | null
  role?: 'chat' | 'embed'
  thinks?: boolean
  tools?: boolean
  match?: boolean
  /** The file holds all its weights (false: a download cut short) */
  complete?: boolean
  needed_bytes?: number | null
}

export interface RegistryContext {
  tokens: number
  preset: string
  vision_preset: string | null
  server: 'gpu' | 'cpu'
  device: Device
  gpu_layers: number
  layers: number
  vram_mb: number
  ram_mb: number
  fits: boolean
  /** Memory from llama-fit-params rather than the header estimate */
  measured: boolean
  tps: number | null
  prompt_tps: number | null
  speed_source: 'measured' | 'scaled' | 'estimate' | null
  load_seconds: number | null
  samples: number
  /** The router's status for this preset */
  status: string | null
}

export type Placement = 'auto' | 'gpu' | 'cpu'

export interface RegistryModel {
  id: string
  name: string
  path: string
  mmproj_path: string | null
  size_bytes: number
  mmproj_bytes: number | null
  info: Partial<GgufInfo>
  role: 'chat' | 'embed'
  reasoning: boolean
  tools: boolean
  vision: boolean
  placement: Placement
  default_context: number
  enabled: boolean
  layers: number
  contexts: RegistryContext[]
  exists: boolean
  /** The file changed since it was measured */
  changed: boolean
  /** Settings that send this model's name (default chat model, embeddings, ...) */
  used_for: string[]
  benchmarked: boolean
  /** The file holds all its weights; an incomplete one is never offered or loaded */
  complete: boolean
  needed_bytes: number | null
  /** The chat model new chats and background work use */
  is_default: boolean
  /** In GPU or CPU memory now */
  loaded: boolean
  last_benchmark: { state: 'running' | 'done' | 'failed'; error?: string | null; results?: Record<string, { gen_tps?: number; error?: string }>; at: number } | null
  /** Context sizes the admin may tick, up to what it was trained for */
  context_steps: number[]
}

export interface GpuInfo {
  name: string
  total_mb: number
  used_mb: number
  llama_mb: number
  others_mb: number
  /** llama-server processes no router runs, holding VRAM a router cannot free */
  stray?: { pid: number; mb: number }[]
  available_mb: number
}

export interface RouterStatus {
  url: string
  online: boolean
  serves_registry: boolean
  missing: string[]
  loaded: string[]
}

export interface Registry {
  models: RegistryModel[]
  gpu: GpuInfo | null
  servers: { gpu: RouterStatus; cpu: RouterStatus }
  benchmark: { model?: string; model_id?: string; context?: number; step?: number; of?: number; state: 'running' | 'done' | 'failed'; error?: string; at: number } | null
  writable: boolean
  read_only_reason: string | null
  fit_tool: boolean
  roots: string[]
  margin_mb: number
}

export interface BrowseEntry {
  name: string
  path: string
  kind: 'dir' | 'model' | 'mmproj'
  size_bytes: number | null
  parts?: number
}

export interface Browse {
  path: string
  parent: string | null
  /** Where the browser can start: the model folders, then Home and the whole disk. */
  places: { name: string; path: string }[]
  entries: BrowseEntry[]
}

export interface Inspection {
  info: GgufInfo
  name: string
  contexts: number[]
  default_context: number
  projectors: GgufInfo[]
  reasoning: boolean
  tools: boolean
  preview: ({ tokens: number } & Pick<RegistryContext, 'device' | 'gpu_layers' | 'layers' | 'vram_mb' | 'ram_mb' | 'fits'>)[]
  already: boolean
}

export interface ModelFields {
  name?: string
  mmproj_path?: string | null
  role?: 'chat' | 'embed'
  reasoning?: boolean
  tools?: boolean
  placement?: Placement
  contexts?: number[]
  default_context?: number
  enabled?: boolean
}

const KEY = ['model-registry']

export const useRegistry = (poll = false) =>
  useQuery({
    queryKey: KEY,
    queryFn: async () => (await apiClient.get<Registry>('/models')).data,
    // While a benchmark runs (or a model was just added and is being measured), keep the numbers fresh.
    refetchInterval: (q) => (poll || q.state.data?.benchmark?.state === 'running' ? 2000 : false),
  })

/** A folder on the server (null: the first place). The last folder stays shown while the next one loads. */
export const useBrowse = (path: string | null, enabled = true) =>
  useQuery({
    queryKey: ['model-browse', path],
    queryFn: async () => (await apiClient.get<Browse>('/models/browse', { params: { path: path ?? undefined } })).data,
    enabled,
    placeholderData: keepPreviousData,
  })

export const inspectModel = async (path: string) => (await apiClient.post<Inspection>('/models/inspect', { path })).data

function useRegistryMutation<T, R = unknown>(fn: (body: T) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEY })
      void qc.invalidateQueries({ queryKey: ['chat-models'] })
    },
  })
}

export const useAddModel = () =>
  useRegistryMutation((body: ModelFields & { path: string }) => apiClient.post<RegistryModel>('/models', body).then((r) => r.data))

export const useUpdateModel = () =>
  useRegistryMutation(({ id, ...body }: ModelFields & { id: string }) => apiClient.patch<RegistryModel>(`/models/${id}`, body).then((r) => r.data))

export const useRemoveModel = () => useRegistryMutation((id: string) => apiClient.delete(`/models/${id}`))

export const useBenchmark = () =>
  useRegistryMutation(({ id, force }: { id: string; force: boolean }) => apiClient.post(`/models/${id}/benchmark`, { force }))

export const useMakeDefault = () => useRegistryMutation((id: string) => apiClient.post(`/models/${id}/default`))

/** Unload a model now. ``reloaded_by``: background work that used it lately and will load it again unless paused. */
export const useUnloadModel = () =>
  useRegistryMutation((id: string) => apiClient.post<{ unloaded: string[]; reloaded_by: string[] }>(`/models/${id}/unload`).then((r) => r.data))
