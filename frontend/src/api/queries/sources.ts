import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { Source } from '../client'

export const useSources = () => {
  return useQuery({
    queryKey: ['sources'],
    queryFn: async () => {
      const { data } = await apiClient.get<Source[]>('/sources')
      return data
    }
  })
}

export const useToggleSource = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, is_active }: { id: string, is_active: boolean }) => {
      const { data } = await apiClient.put(`/sources/${id}/toggle`, { is_active })
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    }
  })
}

export interface PreviewResponse {
  source_type: string
  source_name: string
  sample_items: {
    title: string
    url: string
    published_at?: string
    summary?: string
  }[]
}

export const useAddSource = () => {
  return useMutation({
    mutationFn: async ({ url, confirm = false }: { url: string, confirm?: boolean }) => {
      const { data } = await apiClient.post<PreviewResponse | Source>('/sources', { url, confirm })
      return data
    }
  })
}
