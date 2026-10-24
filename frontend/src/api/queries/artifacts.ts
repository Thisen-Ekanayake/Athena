import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { IndexStatus } from './projects'

/** An artifact as a chat message mentions it. */
export interface ArtifactRef {
  id: string
  title: string
  version: number
}

export interface ArtifactSummary extends ArtifactRef {
  project_id: string | null
  conversation_id: string | null
  index_status: IndexStatus
  created_at: string
  updated_at: string
  chars: number
}

export interface Artifact extends ArtifactSummary {
  content: string
}

export interface ArtifactVersion {
  version: number
  title: string
  author: 'model' | 'user'
  chars: number
  message_id: string | null
  created_at: string
}

const refresh = (qc: ReturnType<typeof useQueryClient>, a: Artifact) => {
  qc.setQueryData(['artifact', a.id], a)
  qc.invalidateQueries({ queryKey: ['artifact-versions', a.id] })
  qc.invalidateQueries({ queryKey: ['chat'] })
  qc.invalidateQueries({ queryKey: ['project'] })
}

export const useArtifact = (id: string | null) =>
  useQuery({
    queryKey: ['artifact', id],
    queryFn: async () => (await apiClient.get<Artifact>(`/artifacts/${id}`)).data,
    enabled: !!id,
  })

export const useArtifactVersions = (id: string | null, enabled = true) =>
  useQuery({
    queryKey: ['artifact-versions', id],
    queryFn: async () => (await apiClient.get<{ versions: ArtifactVersion[] }>(`/artifacts/${id}/versions`)).data.versions,
    enabled: !!id && enabled,
  })

export const fetchArtifactVersion = async (id: string, version: number) =>
  (await apiClient.get<{ version: number; title: string; content: string }>(`/artifacts/${id}/versions/${version}`)).data

export const artifactExportUrl = (id: string) => `${apiClient.defaults.baseURL}/artifacts/${id}/export`

export const useCreateArtifact = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { title: string; content?: string; project_id?: string; chat_id?: string }) =>
      (await apiClient.post<Artifact>('/artifacts', body)).data,
    onSuccess: (a) => refresh(qc, a),
  })
}

export const useUpdateArtifact = (id: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { title?: string; content?: string }) => (await apiClient.patch<Artifact>(`/artifacts/${id}`, body)).data,
    onSuccess: (a) => refresh(qc, a),
  })
}

export const useRestoreArtifact = (id: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (version: number) => (await apiClient.post<Artifact>(`/artifacts/${id}/restore`, { version })).data,
    onSuccess: (a) => refresh(qc, a),
  })
}

export const useDeleteArtifact = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/artifacts/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chat'] })
      qc.invalidateQueries({ queryKey: ['project'] })
    },
  })
}
