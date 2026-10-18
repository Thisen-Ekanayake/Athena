import { useQuery } from '@tanstack/react-query'
import { apiClient, type FeedItem } from '../client'

export interface LibrarySearchResponse {
  query: string
  items: FeedItem[]
  total: number
}

export const useSearch = (q: string, category: string | null = null, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['search', q, category],
    queryFn: async () => {
      const { data } = await apiClient.get<LibrarySearchResponse>('/search', {
        params: { q, category }
      })
      return data
    },
    enabled: enabled && q.length > 2,
    staleTime: 60 * 1000
  })
}
