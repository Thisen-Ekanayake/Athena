import { useQuery, useInfiniteQuery } from '@tanstack/react-query'
import { apiClient, type FeedItem, type FeedResponse, type ClusterInfo } from './client'

export type FeedSort = 'score' | 'date' | 'trending' | 'foryou'

export const useFeed = (
  sort: FeedSort = 'score',
  category: string | null = null,
  dateRange: '24h' | '7d' | '30d' | 'all' = 'all',
  sourceId: string | null = null,
  limit: number = 20,
  unread: boolean = false,
) => {
  return useInfiniteQuery<FeedResponse>({
    queryKey: ['feed', sort, category, dateRange, sourceId, limit, unread],
    queryFn: async ({ pageParam = 1 }) => {
      const { data } = await apiClient.get<FeedResponse>('/feed', {
        params: { sort, category, date_range: dateRange !== 'all' ? dateRange : undefined, source_id: sourceId, page: pageParam, limit, unread: unread || undefined }
      })
      return data
    },
    getNextPageParam: (lastPage) => 
      lastPage.pagination.has_next ? lastPage.pagination.page + 1 : undefined,
    initialPageParam: 1,
  })
}

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

export interface ItemDetail extends FeedItem {
  abstract: string | null
  fetched_at: string | null
  summarised_at: string | null
}

export const useItemDetail = (itemId: string, enabled: boolean = false) => {
  return useQuery({
    queryKey: ['item', itemId],
    queryFn: async () => {
      const { data } = await apiClient.get<ItemDetail>(`/items/${itemId}`)
      return data
    },
    enabled
  })
}
