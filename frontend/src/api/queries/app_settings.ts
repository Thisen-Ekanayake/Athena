import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

export interface ApiKeyInfo {
  key: string
  masked_value: string | null
  is_set: boolean
  updated_at: string | null
}

export const useApiKeys = () => {
  return useQuery({
    queryKey: ['api-keys'],
    queryFn: async () => {
      const { data } = await apiClient.get<ApiKeyInfo[]>('/settings/keys')
      return data
    },
  })
}

export const useSetApiKey = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ key, value }: { key: string; value: string }) => {
      const { data } = await apiClient.post<ApiKeyInfo>(`/settings/keys/${key}`, { value })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })
}

export const useDeleteApiKey = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (key: string) => {
      await apiClient.delete(`/settings/keys/${key}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })
}

/** Model endpoints and names (not secrets). Empty values fall back to the environment, then the default. */
export interface ModelSettings {
  values: Record<string, string>
  defaults: Record<string, string>
  effective: { chat_base_url: string; chat_model: string; embed_base_url: string; embed_model: string; llama_cpp: boolean }
  embed_spaces: { feed: string | null; evolution: string | null }
}

export interface ModelTestResult {
  ok: boolean
  latency_ms: number
  model?: string
  reply?: string
  dimensions?: number
  error?: string
}

export const useModelSettings = () =>
  useQuery({
    queryKey: ['model-settings'],
    queryFn: async () => (await apiClient.get<ModelSettings>('/settings/models')).data,
  })

export const useUpdateModelSettings = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (values: Record<string, string>) =>
      (await apiClient.put<ModelSettings>('/settings/models', { values })).data,
    onSuccess: (data) => queryClient.setQueryData(['model-settings'], data),
  })
}

export const useTestModels = () =>
  useMutation({
    mutationFn: async () =>
      (await apiClient.post<{ chat: ModelTestResult; embed: ModelTestResult }>('/settings/models/test')).data,
  })

// ── Scoring weights (admin) ───────────────────────────────────────────

export const BASE_SIGNALS = ['citation', 'engagement', 'sentiment', 'recency', 'authority'] as const
export type BaseSignal = (typeof BASE_SIGNALS)[number]

export type CategoryWeights = Record<BaseSignal, number> & { preference: number; half_life_days: number }

export interface ScoringSettings {
  categories: Record<string, CategoryWeights & { version: number | null; source: 'saved' | 'default' }>
  defaults: Record<string, CategoryWeights>
  rescoring?: boolean
}

export const useScoringSettings = () =>
  useQuery({
    queryKey: ['scoring-settings'],
    queryFn: async () => (await apiClient.get<ScoringSettings>('/settings/scoring')).data,
  })

export const useUpdateScoring = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (categories: Record<string, CategoryWeights>) =>
      (await apiClient.put<ScoringSettings>('/settings/scoring', { categories })).data,
    onSuccess: (data) => {
      queryClient.setQueryData(['scoring-settings'], data)
      queryClient.invalidateQueries({ queryKey: ['score-breakdown'] })
      queryClient.invalidateQueries({ queryKey: ['feed'] })
    },
  })
}
