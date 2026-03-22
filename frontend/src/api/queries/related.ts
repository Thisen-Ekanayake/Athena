import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { FeedItem } from '../client'

export const useRelatedItems = (itemId: string | null) => {
  return useQuery({
    queryKey: ['related', itemId],
    queryFn: async () => {
      const { data } = await apiClient.get<FeedItem[]>(`/items/${itemId}/related`, {
        params: { limit: 5 }
      })
      return data
    },
    enabled: !!itemId,
    staleTime: 5 * 60 * 1000
  })
}
