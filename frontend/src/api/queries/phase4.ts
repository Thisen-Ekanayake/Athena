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
  is_trending: boolean
}

export interface ScoreBreakdown {
  score: number
  signals: {
    label: string
    value: number
    max_value: number
    weight: number
  }[]
  computed_at: string
  is_trending: boolean
}

const SIGNAL_LABELS: Record<string, string> = {
  citation_impact: 'Citation Impact',
  engagement: 'Engagement',
  community_sentiment: 'Sentiment',
  recency_velocity: 'Recency',
  source_authority: 'Authority',
}

export const useScoreBreakdown = (itemId: string, enabled: boolean) => {
  return useQuery({
    queryKey: ['score-breakdown', itemId],
    queryFn: async (): Promise<ScoreBreakdown> => {
      const { data } = await apiClient.get<ApiScoreBreakdown>(`/items/${itemId}/score-breakdown`)
      const signals = Object.entries(data.signals ?? {}).map(([key, s]) => ({
        label: SIGNAL_LABELS[key] ?? key,
        value: s.score,
        max_value: 1,
        weight: s.weight,
      }))
      return {
        score: data.composite_score,
        signals,
        computed_at: data.computed_at,
        is_trending: data.is_trending,
      }
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

export interface ClusterSummary {
  id: string
  label: string | null
  summary: string | null
  item_count: number
  is_active: boolean
}

export const useClusters = () => {
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

export interface ScoringHealth {
  total_items: number
  scored_items: number
  unscored_items: number
  trending_items: number
  average_score: number
  scoring_queue_depth: number
  trending_percentage: number
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
