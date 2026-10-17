import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../client'

interface ApiSignal {
  score: number
  label: string
  weight: number
}

interface ApiScoreBreakdown {
  composite_score: number
  signals: Record<string, ApiSignal>
  computed_at: string
}

export interface ScoreBreakdown {
  score: number
  signals: {
    key: string
    label: string
    value: number
    max_value: number
    weight: number
  }[]
  computed_at: string
}

const SIGNAL_LABELS: Record<string, string> = {
  citation_impact: 'Citations',
  engagement: 'Engagement',
  recency: 'Recency',
  source_authority: 'Source authority',
  your_interests: 'Your interests',
}

export const useScoreBreakdown = (itemId: string, enabled: boolean) => {
  return useQuery({
    queryKey: ['score-breakdown', itemId],
    queryFn: async (): Promise<ScoreBreakdown> => {
      const { data } = await apiClient.get<ApiScoreBreakdown>(`/items/${itemId}/score-breakdown`)
      const signals = Object.entries(data.signals ?? {}).map(([key, s]) => ({
        key,
        label: SIGNAL_LABELS[key] ?? key,
        value: s.score,
        max_value: 1,
        weight: s.weight,
      }))
      return {
        score: data.composite_score,
        signals,
        computed_at: data.computed_at,
      }
    },
    enabled,
    staleTime: 5 * 60 * 1000
  })
}

export interface ScoringHealth {
  total_items: number
  scored_items: number
  unscored_items: number
  average_score: number
  scoring_queue_depth: number
}

export const useScoringHealth = () => {
  return useQuery({
    queryKey: ['health-scoring'],
    queryFn: async () => {
      const { data } = await apiClient.get<ScoringHealth>('/health/scoring')
      return data
    },
    staleTime: 60 * 1000,
  })
}

export interface FetchHealth {
  total_fetches: number
  successful_fetches: number
  failed_fetches: number
  success_rate: number
}

export const useFetchHealth = () => {
  return useQuery({
    queryKey: ['health-fetch'],
    queryFn: async () => {
      const { data } = await apiClient.get<FetchHealth>('/health/fetch')
      return data
    },
    staleTime: 60 * 1000,
  })
}

export interface SummaryStatus {
  /** Items at each summary status: pending, complete, failed, lazy (written when opened), skipped */
  counts: Record<string, number>
  /** Items skipped for too little text, by source and reason, most first */
  skipped: { source: string; reason: string; count: number }[]
}

export const useSummaryStatus = () =>
  useQuery({
    queryKey: ['health-summaries'],
    queryFn: async () => (await apiClient.get<SummaryStatus>('/admin/summaries/status')).data,
    staleTime: 60 * 1000,
  })
