import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { ChatSummary } from './chats'
import type { ArtifactSummary } from './artifacts'

export type ItemKind = 'paper' | 'map' | 'review' | 'idea_check' | 'list'
export type IndexStatus = 'pending' | 'indexed' | 'failed' | 'none'

export interface ProjectCounts {
  chats: number
  items: number
  files: number
  artifacts: number
}

export interface ProjectSummary {
  id: string
  name: string
  description: string
  instructions: string
  created_at: string
  updated_at: string
  counts: ProjectCounts
}

export interface ProjectItem {
  id: string
  kind: ItemKind
  /** item:<id>, paper:<id>, map:<id>, review:<id>, idea:<id>, list:<id>, or ext:<doi|arxiv|url> */
  ref: string
  title: string
  subtitle: string | null
  /** A page in Athena, if it has one */
  link: string | null
  url?: string | null
  slug?: string
  built?: boolean
  index_status: IndexStatus
  index_error: string | null
  added_at: string
}

export interface UserFile {
  id: string
  filename: string
  mime: string
  kind: 'pdf' | 'text' | 'image'
  size: number
  pages: number | null
  status: 'pending' | 'ready' | 'failed'
  error: string | null
  index_status: IndexStatus
  chars: number
  caption: string | null
  project_id: string | null
  conversation_id: string | null
  created_at: string
}

export interface Project extends ProjectSummary {
  items: ProjectItem[]
  files: UserFile[]
  artifacts: ArtifactSummary[]
  chats: ChatSummary[]
}

/** What to add: something of Athena's by id (maps by slug), or a paper found outside it by its details. */
export interface ItemToAdd {
  kind: ItemKind
  id?: string
  meta?: { title: string; abstract?: string | null; url?: string | null; year?: number | null; authors?: string[]; external_id?: string | null; source?: string | null }
}

export const fileUrl = (id: string, download = false) =>
  `${apiClient.defaults.baseURL}/files/${id}/content${download ? '?download=true' : ''}`

export const useProjects = () =>
  useQuery({
    queryKey: ['projects'],
    queryFn: async () => (await apiClient.get<{ projects: ProjectSummary[] }>('/projects')).data.projects,
  })

/** One project, polled while anything in it is still being indexed. */
export const useProject = (id: string | undefined) =>
  useQuery({
    queryKey: ['project', id],
    queryFn: async () => (await apiClient.get<Project>(`/projects/${id}`)).data,
    enabled: !!id,
    refetchInterval: (q) => {
      const p = q.state.data
      const busy = p && ([...p.items, ...p.files, ...p.artifacts] as { index_status: IndexStatus }[]).some((x) => x.index_status === 'pending')
      return busy ? 4000 : false
    },
  })

/** The projects that hold ``ref`` (item:<id>, map:<slug>, review:<id>, idea:<id>, list:<id>). */
export const useMembership = (ref: string, enabled = true) =>
  useQuery({
    queryKey: ['projects', 'membership', ref],
    queryFn: async () => (await apiClient.get<{ project_ids: string[] }>('/projects/membership', { params: { ref } })).data.project_ids,
    enabled,
  })

export const useCreateProject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { name: string; description?: string; instructions?: string }) =>
      (await apiClient.post<Project>('/projects', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export const useUpdateProject = (id: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { name?: string; description?: string; instructions?: string }) =>
      (await apiClient.patch<ProjectSummary>(`/projects/${id}`, body)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', id] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export const useDeleteProject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/projects/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['chats'] })
    },
  })
}

export const useAddToProject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, item }: { projectId: string; item: ItemToAdd }) =>
      (await apiClient.post<ProjectItem & { created: boolean }>(`/projects/${projectId}/items`, item)).data,
    onSuccess: (_d, { projectId }) => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export const useRemoveFromProject = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, itemId }: { projectId: string; itemId: string }) => {
      await apiClient.delete(`/projects/${projectId}/items/${itemId}`)
    },
    onSuccess: (_d, { projectId }) => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export const useReindexProject = (id: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${id}/reindex`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['project', id] }),
  })
}

const form = (files: File[]) => {
  const body = new FormData()
  files.forEach((f) => body.append('files', f))
  return body
}

export const useUploadProjectFiles = (projectId: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (files: File[]) =>
      (await apiClient.post<{ files: UserFile[] }>(`/projects/${projectId}/files`, form(files))).data.files,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['project', projectId] }),
  })
}

export const uploadChatFiles = async (chatId: string, files: File[]) =>
  (await apiClient.post<{ files: UserFile[] }>(`/chats/${chatId}/files`, form(files))).data.files

export const useDeleteFile = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/files/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['project'] }),
  })
}
