import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import { queryClient } from '../queryClient'
import type { ArtifactRef, ArtifactSummary } from './artifacts'
import type { UserFile } from './projects'

export type Effort = 'off' | 'low' | 'medium' | 'high'

/** Where a model loads at one context: all on the GPU, split between GPU and CPU, or all on the CPU. */
export type Device = 'gpu' | 'split' | 'cpu'

/** One context size a registered model offers, with where it loads and how fast it answers there. */
export interface ModelContext {
  tokens: number
  device: Device
  gpu_layers: number
  layers: number
  vram_mb: number
  ram_mb: number
  fits: boolean
  /** Answer tokens a second */
  tps: number | null
  prompt_tps: number | null
  /** measured: benchmarked or from chats; scaled: from another context; estimate: from the bandwidth formula */
  speed_source: 'measured' | 'scaled' | 'estimate' | null
  load_seconds: number
  server: 'gpu' | 'cpu'
  loaded: boolean
}

export interface ChatModel {
  id: string
  /** Thinks: the chat offers it an effort */
  reasoning: boolean
  /** Takes images (it has a vision projector) */
  vision: boolean
  /** Its template takes tool calls: search, maps, artifacts */
  tools: boolean
  context: number
  loaded: boolean
  /** From the model registry: the contexts users may pick */
  contexts?: ModelContext[]
  default_context?: number
  loaded_context?: number | null
  size_bytes?: number
  params?: string | null
  quant?: string | null
  architecture?: string | null
}

export interface ChatModels {
  models: ChatModel[]
  default: string
  efforts: { id: Effort; budget: number }[]
  default_effort: Effort
  vision_model: string
  /** The models come from the registry, with contexts */
  registry?: boolean
}

export interface LoadStage {
  label: string
  state: 'done' | 'active' | 'pending'
}

/** How far a model's load has got (GET /chat/models/state, and the stream's loading events). */
export interface LoadState {
  model: string
  preset: string
  context: number
  server: 'gpu' | 'cpu'
  status: 'loaded' | 'loading' | 'waiting' | 'swapping' | 'unloaded' | 'failed' | 'offline' | 'unknown'
  device: { kind: Device; gpu: string | null; gpu_layers: number; layers: number; vram_mb: number; ram_mb: number }
  stages: LoadStage[]
  /** 0..0.99 while loading, timed from the last load */
  progress: number
  eta_seconds: number
  expected_seconds: number
  elapsed_seconds: number
  /** The model the router holds now, which has to go first */
  other: string | null
}

/** How an answer ran */
export interface TurnStats {
  tps?: number | null
  prompt_tps?: number | null
  ttft_ms?: number
  load_ms?: number
  device?: Device
  gpu_layers?: number
  layers?: number
  context?: number
  /** What the context held at the end of the answer: the last call's prompt and answer tokens */
  context_used?: number
}

export interface ChatSummary {
  id: string
  title: string
  project_id: string | null
  project_name: string | null
  model: string | null
  effort: Effort | null
  /** The context size picked; the model's default when null */
  context?: number | null
  /** Listed first */
  pinned: boolean
  /** Out of the lists; `useChats({ archived: true })` shows only these */
  archived: boolean
  created_at: string
  updated_at: string
}

/** A numbered source an answer cites as [n]: a project passage, a paper a search found, a map passage. */
export interface ChatSource {
  n: number
  kind: string
  title: string
  link?: string | null
  excerpt?: string
  source?: string
  score?: number
  map?: string
  section?: string
}

export interface SearchResult {
  n: number
  title: string
  year: number | null
  authors: string[]
  url: string | null
  source: string
  /** In Athena's feed: added by id */
  item_id: string | null
  /** Found outside Athena: added with these details */
  meta: { title: string; abstract?: string | null; url?: string | null; year?: number | null; authors?: string[]; external_id?: string | null; source?: string | null } | null
  in_project: boolean
}

export interface ToolStep {
  id: string
  tool: string
  label: string
  args: Record<string, unknown>
  status: 'running' | 'done' | 'failed'
  summary?: string
  results?: SearchResult[]
  map?: string
  artifact?: ArtifactRef
}

/** A map paper an answer named by id (A3), from the graph the model was given. */
export interface MapRef {
  slug: string
  map: string
  paper_id: string
  label: string
  year: number | null
}

/** A research map attached to a chat. With ``share`` the model gets it as a graph; otherwise only the user sees it. */
export interface ChatMap {
  topic_id: string
  slug: string
  name: string
  description: string | null
  share: boolean
  /** Its letter in the chat: its papers are A1, A2… */
  key: string
  built: boolean
  built_at: string | null
  added_at: string
  papers?: number
  milestones?: number
}

/** A map to attach: its id or slug, and whether the model gets it */
export interface MapPick {
  id: string
  share: boolean
}

export interface MapDigest {
  key: string
  share: boolean
  /** Tokens this map may take on the next turn */
  budget: number
  /** The level the next turn would use */
  level: 'full' | 'compact' | 'minimal'
  levels: Record<'full' | 'compact' | 'minimal', { text: string; tokens: number }>
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning: string | null
  reasoning_ms: number | null
  steps: ToolStep[]
  sources: ChatSource[]
  attachments: { id: string; filename: string; kind: UserFile['kind'] }[]
  artifacts: ArtifactRef[]
  /** The map papers the answer named, by id */
  map_refs?: Record<string, MapRef>
  model: string | null
  effort: Effort | null
  status: 'done' | 'stopped' | 'failed' | 'streaming'
  error: string | null
  input_tokens: number
  output_tokens: number
  stats?: TurnStats | null
  created_at: string
}

export interface Chat extends ChatSummary {
  messages: ChatMessage[]
  files: UserFile[]
  maps: ChatMap[]
  artifacts: ArtifactSummary[]
}

export const useChatModels = () =>
  useQuery({
    queryKey: ['chat-models'],
    queryFn: async () => (await apiClient.get<ChatModels>('/chat/models')).data,
    staleTime: 5_000,  // which context is loaded changes under the page (a benchmark, background work)
  })

const SETTLED = new Set<LoadState['status']>(['loaded', 'failed', 'offline', 'unknown'])

/** Start loading a model now (picked, or the user started typing); the state comes back. */
export const warmModel = async (body: { model: string; context?: number | null; vision?: boolean }) =>
  (await apiClient.post<LoadState>('/chat/models/warm', body)).data

/** How far a model's load has got, polled while it is under way; once in, the picker hears it is loaded. */
export const useModelState = (model: string, context: number | null | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ['model-state', model, context ?? null],
    queryFn: async () => {
      const state = (await apiClient.get<LoadState>('/chat/models/state', { params: { model, context: context ?? undefined } })).data
      if (state.status === 'loaded') void queryClient.invalidateQueries({ queryKey: ['chat-models'] })
      return state
    },
    enabled: enabled && !!model,
    refetchInterval: (q) => (q.state.data && SETTLED.has(q.state.data.status) ? false : 600),
  })

export const useChats = (params: { projectId?: string; standalone?: boolean; q?: string; limit?: number; archived?: boolean } = {}) =>
  useQuery({
    queryKey: ['chats', params],
    queryFn: async () =>
      (await apiClient.get<{ chats: ChatSummary[] }>('/chats', {
        params: {
          project_id: params.projectId, standalone: params.standalone || undefined, q: params.q || undefined, limit: params.limit,
          archived: params.archived || undefined,
        },
      })).data.chats,
  })

export const useChat = (id: string | undefined) =>
  useQuery({
    queryKey: ['chat', id],
    queryFn: async () => (await apiClient.get<Chat>(`/chats/${id}`)).data,
    enabled: !!id,
  })

export const createChat = async (body: { project_id?: string | null; model?: string; effort?: Effort; context?: number | null }) =>
  (await apiClient.post<ChatSummary>('/chats', body)).data

export const useUpdateChat = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: string; title?: string; project_id?: string | null; pinned?: boolean; archived?: boolean }) =>
      (await apiClient.patch<ChatSummary>(`/chats/${id}`, body)).data,
    onSuccess: (chat) => {
      qc.invalidateQueries({ queryKey: ['chats'] })
      qc.invalidateQueries({ queryKey: ['chat', chat.id] })
      qc.invalidateQueries({ queryKey: ['project'] })
    },
  })
}

export const useDeleteChat = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/chats/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chats'] })
      qc.invalidateQueries({ queryKey: ['project'] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export const attachChatMaps = async (chatId: string, maps: MapPick[]) =>
  (await apiClient.post<{ maps: ChatMap[] }>(`/chats/${chatId}/maps`, { maps })).data.maps

export const useAttachChatMaps = (chatId: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (maps: MapPick[]) => attachChatMaps(chatId, maps),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat', chatId] }),
  })
}

export const useShareChatMap = (chatId: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ topic, share }: { topic: string; share: boolean }) =>
      (await apiClient.patch<{ maps: ChatMap[] }>(`/chats/${chatId}/maps/${topic}`, { share })).data.maps,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat', chatId] })
      qc.invalidateQueries({ queryKey: ['map-digest', chatId] })
    },
  })
}

export const useDetachChatMap = (chatId: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (topic: string) => {
      await apiClient.delete(`/chats/${chatId}/maps/${topic}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat', chatId] }),
  })
}

/** The graph the model gets for a map in this chat. */
export const useMapDigest = (chatId: string | undefined, topic: string, enabled: boolean) =>
  useQuery({
    queryKey: ['map-digest', chatId, topic],
    queryFn: async () => (await apiClient.get<MapDigest>(`/chats/${chatId}/maps/${topic}/digest`)).data,
    enabled: enabled && !!chatId,
  })

/** Take a file out of the chat's turns, or bring it back. */
export const useDetachChatFile = (chatId: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ fileId, detached }: { fileId: string; detached: boolean }) =>
      (await apiClient.patch<UserFile>(`/chats/${chatId}/files/${fileId}`, { detached })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat', chatId] }),
  })
}
