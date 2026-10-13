import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'

export type TopicStatus = 'pending' | 'building' | 'refining' | 'ready' | 'failed'

export interface EvolutionTopic {
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
}

/** Building, or not built yet: the map cannot be read. */
export const isBuilding = (status: TopicStatus) => status === 'pending' || status === 'building'
/** The worker still has something to do for this topic. */
export const isBusy = (status: TopicStatus) => isBuilding(status) || status === 'refining'

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
  status: 'persisting' | 'new' | 'addressed' | 'quiet'
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
export const useTopicStatus = (slug: string) =>
  useQuery({
    queryKey: ['evolution', 'status', slug],
    queryFn: async () => (await apiClient.get<EvolutionTopic>(`/evolution/topics/${slug}`)).data,
    refetchInterval: (query) => (query.state.data && isBusy(query.state.data.status) ? 2500 : false),
  })

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

/** ``version`` (status and build time) refetches the map when a build or refinement finishes. */
export const useTopicGraph = (slug: string | undefined, limit: number, version = '', enabled = true) =>
  useQuery({
    queryKey: ['evolution', 'graph', slug, limit, version],
    queryFn: async () =>
      (await apiClient.get<EvolutionGraph>(`/evolution/topics/${slug}/graph`, { params: { limit } })).data,
    enabled: !!slug && enabled,
    staleTime: 5 * 60 * 1000,
    placeholderData: (previous) => previous,
  })

export const useTopicTimeline = (slug: string | undefined, version = '', enabled = true) =>
  useQuery({
    queryKey: ['evolution', 'timeline', slug, version],
    queryFn: async () => (await apiClient.get<EvolutionTimeline>(`/evolution/topics/${slug}/timeline`)).data,
    enabled: !!slug && enabled,
    staleTime: 5 * 60 * 1000,
    placeholderData: (previous) => previous,
  })

export const topicGapsQuery = (slug: string | undefined) => ({
  queryKey: ['evolution', 'gaps', slug],
  queryFn: async () => (await apiClient.get<TopicGaps>(`/evolution/topics/${slug}/gaps`)).data,
  enabled: !!slug,
  staleTime: 5 * 60 * 1000,
})

export const useTopicGaps = (slug: string | undefined) => useQuery(topicGapsQuery(slug))

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

// ── reading path (E1) ──────────────────────────────────────────────────

export interface ReadingStep extends EvolutionNode {
  position: number
  /** One line on why it matters, written by the chat model; null while it is being written, "" when none could be */
  why: string | null
  read: boolean
  /** Positions of earlier steps it cites */
  builds_on: number[]
  /** Positions of earlier steps whose stated limitation it takes on (strict links) */
  addresses: number[]
}

export interface ReadingPath {
  topic: EvolutionTopic
  n: number
  survey: ReadingStep | null
  other_surveys: EvolutionNode[]
  steps: ReadingStep[]
  read_count: number
  total: number
  notes_pending: boolean
  notes_error: string | null
}

const readingPathKey = (slug: string, n: number) => ['evolution', 'reading-path', slug, n] as const

/** Polled while the notes are being written. */
export const useReadingPath = (slug: string, n: number) =>
  useQuery({
    queryKey: readingPathKey(slug, n),
    queryFn: async () =>
      (await apiClient.get<ReadingPath>(`/evolution/topics/${slug}/reading-path`, { params: { n } })).data,
    placeholderData: (previous) => previous,
    refetchInterval: (query) => (query.state.data?.notes_pending ? 3000 : false),
  })

/** Ticks a paper read or unread. Reading is per paper, so every map's path picks it up. */
export const useMarkRead = (slug: string, n: number) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { paperId: string; read: boolean }) => {
      const url = `/evolution/papers/${vars.paperId}/read`
      await (vars.read ? apiClient.put(url) : apiClient.delete(url))
    },
    onMutate: ({ paperId, read }) => {
      queryClient.setQueryData<ReadingPath>(readingPathKey(slug, n), (path) => {
        if (!path) return path
        const tick = (s: ReadingStep) => (s.id === paperId ? { ...s, read } : s)
        return { ...path, survey: path.survey && tick(path.survey), steps: path.steps.map(tick) }
      })
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'reading-path'] }),
  })
}
