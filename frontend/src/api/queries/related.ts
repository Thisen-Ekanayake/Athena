import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../client'

/** A nearby item by embedding similarity. Slimmer than a feed item: no source or summary. */
export interface RelatedItem {
  id: string
  title: string
  url: string
  score: number
  similarity: number
  category: string
  published_at: string | null
}

export const useRelatedItems = (itemId: string | null) => {
  return useQuery({
    queryKey: ['related', itemId],
    queryFn: async () => {
      const { data } = await apiClient.get<RelatedItem[]>(`/items/${itemId}/related`, {
        params: { limit: 5 }
      })
      return data
    },
    enabled: !!itemId,
    staleTime: 5 * 60 * 1000
  })
}
