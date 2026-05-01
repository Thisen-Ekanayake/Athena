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
