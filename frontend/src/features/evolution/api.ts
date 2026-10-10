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
  strict: boolean // a citing sentence states a limitation of the cited paper, attributed to its own method
  fixes: boolean // ...and claims to fix it
}

export interface LooseEdge {
  source: string // later paper
  target: string // earlier paper whose stated gap its text matches
  score: number
}

export interface EvolutionGraph {
  topic: EvolutionTopic
  nodes: EvolutionNode[]
  edges: EvolutionEdge[]
  loose_edges: LooseEdge[]
  total_papers: number
  strict_links: number
  year_range: [number, number] | null
}

export interface EvolutionTimeline {
  topic: EvolutionTopic
  years: { year: number; papers: EvolutionNode[] }[]
  without_full_text: EvolutionNode[]
}

export interface LinkEvidence {
  sentence: string
  section_type: string | null
  label: 'addresses_limitation' | 'criticises'
  source: 'grobid' | 's2'
}

export interface StrictLink {
  paper: EvolutionNode
  evidence: LinkEvidence[]
}

export interface EvolutionPaperDetail extends EvolutionNode {
  abstract: string | null
  doi: string | null
  arxiv_id: string | null
  openalex_year: number | null
  merged_ids: string[]
  builds_on: EvolutionNode[]
  built_upon_by: EvolutionNode[]
  addresses: StrictLink[] // earlier papers whose stated limitation this one takes on
  addressed_by: StrictLink[] // later papers that take on this one's limitations
  full_text: { status?: 'parsed' | 'failed' | 's2_contexts'; sections?: number; contexts?: number; error?: string }
  gaps: PaperGap[]
  loose_matches: LooseMatch[]
}

export interface PaperGap {
  sentence: string
  origin: 'own' | 'citing'
  section_type: string | null
  theme: string | null
  stated_by: EvolutionNode | null // the later paper, for gaps stated about this one
}

export interface LooseMatch {
  paper: EvolutionNode
  score: number
  cites: boolean
  gap: string
  passage: string
  section_type: string
}

export interface MiniPaper {
  id: string
  title: string
  year: number | null
  named_method: string | null
  is_milestone: boolean
}

export interface GapTheme {
  id: string
  label: string
  size: number
  status: 'persisting' | 'addressed' | 'quiet'
  first_year: number | null
  last_year: number | null
  yearly: { year: number; count: number }[]
  own: number
  citing: number
  papers: MiniPaper[]
  fixed_by: MiniPaper[]
  examples: { sentence: string; origin: 'own' | 'citing'; section_type: string | null; paper: MiniPaper | null; stated_by: MiniPaper | null }[]
  loose_candidates: { paper: MiniPaper; score: number }[]
}

export interface TopicGaps {
  topic: EvolutionTopic
  latest_year: number | null
  themes: GapTheme[]
  loose_min_score: number
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

export const useTopicGaps = (slug: string | undefined) =>
  useQuery({
    queryKey: ['evolution', 'gaps', slug],
    queryFn: async () => (await apiClient.get<TopicGaps>(`/evolution/topics/${slug}/gaps`)).data,
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
