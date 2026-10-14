import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

export type ReviewStatus = 'queued' | 'running' | 'done' | 'failed'

export interface ReviewSummary {
  id: string
  title: string
  query: string | null
  /** map: grounded in a research map; abstracts: from search results' abstracts only */
  mode: 'map' | 'abstracts'
  status: ReviewStatus
  topic: { slug: string; name: string } | null
  progress: { step?: number; of?: number; label?: string; at?: string }
  cited: number
  created_at: string | null
  finished_at: string | null
}

export interface ReviewSection {
  key: string
  title: string
  level: number
  markdown: string
}

export interface ReviewSource {
  n: number
  title: string
  year: number | null
  authors: string[]
  venue?: string | null
  doi?: string | null
  arxiv_id?: string | null
  url?: string | null
  name?: string | null
}

export interface Review extends ReviewSummary {
  sections: ReviewSection[]
  sources: ReviewSource[]
  markdown: string | null
  error: string | null
  model: string | null
  input_tokens: number
  output_tokens: number
  built_at: string | null
}

export const isWriting = (r?: { status: ReviewStatus } | null) => r?.status === 'queued' || r?.status === 'running'

export const useReviews = () =>
  useQuery({
    queryKey: ['reviews'],
    queryFn: async () => (await apiClient.get<{ reviews: ReviewSummary[] }>('/reviews')).data.reviews,
    refetchInterval: (q) => (q.state.data?.some(isWriting) ? 5000 : false),
  })

/** One review, polled every few seconds while it is being written. */
export const useReview = (id: string | null | undefined) =>
  useQuery({
    queryKey: ['reviews', id],
    queryFn: async () => (await apiClient.get<Review>(`/reviews/${id}`)).data,
    enabled: !!id,
    refetchInterval: (q) => (isWriting(q.state.data) ? 2500 : false),
  })

/** Start a review: of a map (``topic_slug``), or of a query, grounded in a map when one matches. */
export const useStartReview = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { query?: string; topic_slug?: string }) =>
      (await apiClient.post<ReviewSummary>('/reviews', body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reviews'] }),
  })
}

export const useDeleteReview = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/reviews/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reviews'] }),
  })
}
