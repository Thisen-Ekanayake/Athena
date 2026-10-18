/** Topics: listing, matching, proposals, building, rebuilding and deleting maps. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { useMapScope } from './scope'

export type TopicStatus = 'pending' | 'building' | 'refining' | 'ready' | 'failed'

export interface EvolutionTopic {
  /** Null only for responses from before topic ids were sent */
  id: string | null
  slug: string
  name: string
  aliases: string[]
  description: string | null
  /** refining: the map can be read while its abstracts are embedded and it is rebuilt */
  status: TopicStatus
  status_detail: string | null
  built_at: string | null
  origin: 'curated' | 'search'
  query: string | null
  /** The last build's summary; s2 is "used", "off" or "skipped (reason)" */
  build_stats: Record<string, string | number> & { s2?: string; refine?: string; papers?: number }
  paper_count?: number
  milestone_count?: number
  /** The latest snapshot that changed something (E4) */
  last_change?: { taken_at: string; new_milestones: number; new_gaps: number; solved_gaps: number; papers_added: number } | null
}

/** Building, or not built yet: the map cannot be read. */
export const isBuilding = (status: TopicStatus) => status === 'pending' || status === 'building'

/** The worker still has something to do for this topic. */
export const isBusy = (status: TopicStatus) => isBuilding(status) || status === 'refining'

export interface TopicMatch {
  /** alias: the query names the topic; semantic or text: the topic's papers match it */
  method: 'alias' | 'semantic' | 'text'
}

export type TopicSearchResult =
  | { found: true; query: string; topic: EvolutionTopic; match: TopicMatch }
  | { found: false; query: string; message: string; available: string[] }

export interface ProposalCandidate {
  openalex_id: string
  alt_ids: string[]
  title: string
  year: number | null
  citations: number
  kind: 'method' | 'survey' | 'dataset' | 'benchmark'
  venue: string | null
  title_match: boolean
  semantic: boolean
}

export type RefineStatus = 'pending' | 'running' | 'done' | 'failed' | 'unavailable' | 'expired' | 'cancelled'

export interface TopicProposal {
  id: string
  query: string
  name: string
  description: string
  aliases: string[]
  fields: string[]
  field_counts: [string, number][]
  candidates: ProposalCandidate[]
  anchors: string[]
  keywords: string[]
  keyword_suggestions: string[]
  cost_usd: number
  refine: {
    status: RefineStatus
    model?: string
    error?: string
    name?: string
    description?: string
    aliases?: string[]
    keywords?: string[]
    anchors?: string[]
    anchors_from_model?: boolean
  }
}

export interface NewTopic {
  query: string
  name: string
  description: string
  aliases: string[]
  keywords: string[]
  anchors: { openalex_id: string; alt_ids: string[] }[]
  fields: string[]
  proposal_id: string
}

export const useEvolutionTopics = () =>
  useQuery({
    queryKey: ['evolution', 'topics'],
    queryFn: async () => (await apiClient.get<EvolutionTopic[]>('/evolution/topics')).data,
    // While a map builds, its card shows progress.
    refetchInterval: (query) => (query.state.data?.some((t) => isBusy(t.status)) ? 4000 : false),
  })

export const searchTopics = async (q: string) =>
  (await apiClient.get<TopicSearchResult>('/evolution/search', { params: { q } })).data

export const createProposal = async (query: string) =>
  (await apiClient.post<TopicProposal>('/evolution/proposals', { query })).data

const REFINING: RefineStatus[] = ['pending', 'running']

/** The proposal, polled while the 9B is still at work on it. */
export const useProposal = (initial: TopicProposal) =>
  useQuery({
    queryKey: ['evolution', 'proposal', initial.id],
    queryFn: async () => (await apiClient.get<TopicProposal>(`/evolution/proposals/${initial.id}`)).data,
    initialData: initial,
    refetchInterval: (query) => (REFINING.includes(query.state.data?.refine.status ?? 'done') ? 3000 : false),
  })

export const useCreateTopic = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (topic: NewTopic) => (await apiClient.post<EvolutionTopic>('/evolution/topics', topic)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'topics'] }),
  })
}

/** One topic's status, polled while the worker has something to do for it. */
export const useTopicStatus = (slug: string) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: [scope.key, 'status', slug],
    queryFn: async () => (await apiClient.get<EvolutionTopic>(scope.base(slug))).data,
    refetchInterval: (query) => (query.state.data && isBusy(query.state.data.status) ? 2500 : false),
    retry: scope.readOnly ? false : 3,  // a dead share link is a 404 that stays one
  })
}

export const useRebuildTopic = (slug: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await apiClient.post<EvolutionTopic>(`/evolution/topics/${slug}/rebuild`)).data,
    onSuccess: (topic) => {
      queryClient.setQueryData(['evolution', 'status', slug], topic)
      queryClient.invalidateQueries({ queryKey: ['evolution', 'topics'] })
    },
  })
}

export const useDeleteTopic = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (slug: string) => {
      await apiClient.delete(`/evolution/topics/${slug}`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'topics'] }),
  })
}
