import { useQuery } from '@tanstack/react-query'
import { apiClient, type ClusterInfo, type FeedItem } from '../client'

/** The Clusters page's clusters, optionally of one category. */
export const useClusters = (category: string | null = null) => {
  return useQuery({
    queryKey: ['clusters', category],
    queryFn: async () => {
      const { data } = await apiClient.get<ClusterInfo[]>('/clusters', {
        params: { category }
      })
      return data
    }
  })
}

export interface ClusterDetail {
  cluster: ClusterSummary
  items: FeedItem[]
  pagination: { page: number; limit: number; total: number; has_next: boolean }
}

export const useCluster = (clusterId: string, page: number = 1) => {
  return useQuery({
    queryKey: ['cluster', clusterId, page],
    queryFn: async () => {
      const { data } = await apiClient.get<ClusterDetail>(`/clusters/${clusterId}`, {
        params: { page, limit: 20 }
      })
      return data
    },
    staleTime: 5 * 60 * 1000
  })
}

export interface ClusterSummary {
  id: string
  label: string | null
  summary: string | null
  item_count: number
  is_active: boolean
}

/** Every cluster, inactive ones too, for the command palette and Settings. */
export const useClusterList = () => {
  return useQuery({
    queryKey: ['clusters-list'],
    queryFn: async () => {
      const { data } = await apiClient.get<ClusterSummary[]>('/clusters', {
        params: { min_items: 0 }
      })
      return data
    },
    staleTime: 5 * 60 * 1000,
  })
}
