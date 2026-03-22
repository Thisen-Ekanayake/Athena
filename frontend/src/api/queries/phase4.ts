import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../client'

export interface ScoreBreakdown {
  score: number
  signals: {
    label: string
    value: number
    max_value: number
    weight: number
  }[]
  computed_at: string
}

export const useScoreBreakdown = (itemId: string, enabled: boolean) => {
  return useQuery({
    queryKey: ['score-breakdown', itemId],
    queryFn: async () => {
      const { data } = await apiClient.get<ScoreBreakdown>(`/items/${itemId}/score-breakdown`)
      return data
    },
    enabled,
    staleTime: 5 * 60 * 1000
  })
}

export const useSearch = (q: string, category: string | null = null, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['search', q, category],
    queryFn: async () => {
      const { data } = await apiClient.get<any>('/search', {
        params: { q, category }
      })
      return data
    },
    enabled: enabled && q.length > 2,
    staleTime: 60 * 1000
  })
}

export const useCluster = (clusterId: string, page: number = 1) => {
  return useQuery({
    queryKey: ['cluster', clusterId, page],
    queryFn: async () => {
      const { data } = await apiClient.get<any>(`/clusters/${clusterId}`, {
        params: { page, limit: 20 }
      })
      return data
    },
    staleTime: 5 * 60 * 1000
  })
}
