/** A map's graph, timeline, one paper's detail, milestone pins and rising papers. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { type LooseMatch, type PaperGap } from './gaps'
import { useMapScope } from './scope'
import { type EvolutionTopic } from './topics'

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
  /** OpenAlex's citations per calendar year, oldest first; empty until fetched */
  citations_by_year?: YearCount[]
}

export interface YearCount {
  year: number
  citations: number
  /** The current year, still running */
  partial: boolean
}

export interface RisingPaper extends EvolutionNode {
  last_12_months: number
  previous_12_months: number
  ratio: number
  citations_by_year: YearCount[]
}

/** The map's papers gaining citations fastest (last twelve months against the twelve before). */
export const useTopicRising = (slug: string, limit = 10) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: [scope.key, 'rising', slug, limit],
    queryFn: async () => (await apiClient.get<{ papers: RisingPaper[] }>(`${scope.base(slug)}/rising`, { params: { limit } })).data.papers,
    staleTime: 10 * 60 * 1000,
  })
}

/** ``version`` (status and build time) refetches the map when a build or refinement finishes. */
export const useTopicGraph = (slug: string | undefined, limit: number, version = '', enabled = true) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: [scope.key, 'graph', slug, limit, version],
    queryFn: async () =>
      (await apiClient.get<EvolutionGraph>(`${scope.base(slug!)}/graph`, { params: { limit } })).data,
    enabled: !!slug && enabled,
    staleTime: 5 * 60 * 1000,
    placeholderData: (previous) => previous,
  })
}

export const useTopicTimeline = (slug: string | undefined, version = '', enabled = true) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: [scope.key, 'timeline', slug, version],
    queryFn: async () => (await apiClient.get<EvolutionTimeline>(`${scope.base(slug!)}/timeline`)).data,
    enabled: !!slug && enabled,
    staleTime: 5 * 60 * 1000,
    placeholderData: (previous) => previous,
  })
}

export const usePaperDetail = (slug: string | undefined, paperId: string | null) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: [scope.key, 'paper', slug, paperId],
    queryFn: async () =>
      (await apiClient.get<EvolutionPaperDetail>(`${scope.base(slug!)}/papers/${paperId}`)).data,
    enabled: !!slug && !!paperId,
  })
}

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
