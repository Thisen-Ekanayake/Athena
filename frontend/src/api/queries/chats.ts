import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { ArtifactRef, ArtifactSummary } from './artifacts'
import type { UserFile } from './projects'

export type Effort = 'off' | 'low' | 'medium' | 'high'

export interface ChatModel {
  id: string
  /** Thinks: the chat offers it an effort */
  reasoning: boolean
  vision: boolean
  context: number
  loaded: boolean
}

export interface ChatModels {
  models: ChatModel[]
  default: string
  efforts: { id: Effort; budget: number }[]
  default_effort: Effort
  vision_model: string
}

export interface ChatSummary {
  id: string
  title: string
  project_id: string | null
  project_name: string | null
  model: string | null
  effort: Effort | null
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
  model: string | null
  effort: Effort | null
  status: 'done' | 'stopped' | 'failed' | 'streaming'
  error: string | null
  input_tokens: number
  output_tokens: number
  created_at: string
}

export interface Chat extends ChatSummary {
  messages: ChatMessage[]
  files: UserFile[]
  artifacts: ArtifactSummary[]
}

export const useChatModels = () =>
  useQuery({
    queryKey: ['chat-models'],
    queryFn: async () => (await apiClient.get<ChatModels>('/chat/models')).data,
    staleTime: 30_000,
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

export const createChat = async (body: { project_id?: string | null; model?: string; effort?: Effort }) =>
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
