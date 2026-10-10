import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'

export interface EvolutionTopic {
  slug: string
  name: string
  aliases: string[]
  description: string | null
  status: 'pending' | 'building' | 'ready' | 'failed'
  status_detail: string | null
  built_at: string | null
  paper_count?: number
  milestone_count?: number
}

export type MilestoneOverride = 'pin' | 'unpin' | null

export interface EvolutionNode {
  id: string
  openalex_id: string
  title: string
  year: number | null
  year_source: string | null
  authors: string[]
  venue: string | null
  cited_by_count: number
  kind: 'method' | 'survey' | 'dataset' | 'benchmark'
  role: 'seed' | 'core'
  named_method: string | null
  in_degree: number
  pagerank: number
  citation_percentile: number
  specificity: number
  on_main_path: boolean
  milestone_score: number
  score_detail: Record<string, number>
  is_milestone: boolean
  is_milestone_auto: boolean
  milestone_override: MilestoneOverride
  override_note: string | null
  full_text_status: 'unavailable' | 'available' | 'parsed' | 'failed'
  url: string
}

export interface EvolutionEdge {
  source: string // citing paper
  target: string // cited paper
  main_path: boolean
}

export interface EvolutionGraph {
  topic: EvolutionTopic
  nodes: EvolutionNode[]
  edges: EvolutionEdge[]
  total_papers: number
  year_range: [number, number] | null
}

export interface EvolutionTimeline {
  topic: EvolutionTopic
  years: { year: number; papers: EvolutionNode[] }[]
  without_full_text: EvolutionNode[]
}

export interface EvolutionPaperDetail extends EvolutionNode {
  abstract: string | null
  doi: string | null
  arxiv_id: string | null
  openalex_year: number | null
  merged_ids: string[]
  builds_on: EvolutionNode[]
  built_upon_by: EvolutionNode[]
}

export type TopicSearchResult =
  | { found: true; query: string; topic: EvolutionTopic }
  | { found: false; query: string; message: string; available: string[] }

export const useEvolutionTopics = () =>
  useQuery({
    queryKey: ['evolution', 'topics'],
    queryFn: async () => (await apiClient.get<EvolutionTopic[]>('/evolution/topics')).data,
  })

export const searchTopics = async (q: string) =>
  (await apiClient.get<TopicSearchResult>('/evolution/search', { params: { q } })).data

export const useTopicGraph = (slug: string | undefined, limit: number) =>
  useQuery({
    queryKey: ['evolution', 'graph', slug, limit],
    queryFn: async () =>
      (await apiClient.get<EvolutionGraph>(`/evolution/topics/${slug}/graph`, { params: { limit } })).data,
    enabled: !!slug,
    staleTime: 5 * 60 * 1000,
  })

export const useTopicTimeline = (slug: string | undefined) =>
  useQuery({
    queryKey: ['evolution', 'timeline', slug],
    queryFn: async () => (await apiClient.get<EvolutionTimeline>(`/evolution/topics/${slug}/timeline`)).data,
    enabled: !!slug,
    staleTime: 5 * 60 * 1000,
  })

export const usePaperDetail = (slug: string | undefined, paperId: string | null) =>
  useQuery({
    queryKey: ['evolution', 'paper', slug, paperId],
    queryFn: async () =>
      (await apiClient.get<EvolutionPaperDetail>(`/evolution/topics/${slug}/papers/${paperId}`)).data,
    enabled: !!slug && !!paperId,
  })

export const useSetMilestone = (slug: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { paperId: string; action: 'pin' | 'unpin' | 'reset'; note?: string }) =>
      (
        await apiClient.post<EvolutionPaperDetail>(`/evolution/topics/${slug}/milestones/${vars.paperId}`, {
          action: vars.action,
          note: vars.note || null,
        })
      ).data,
    onSuccess: (detail) => {
      queryClient.setQueryData(['evolution', 'paper', slug, detail.id], detail)
      queryClient.invalidateQueries({ queryKey: ['evolution', 'graph', slug] })
      queryClient.invalidateQueries({ queryKey: ['evolution', 'timeline', slug] })
      queryClient.invalidateQueries({ queryKey: ['evolution', 'topics'] })
    },
  })
}
