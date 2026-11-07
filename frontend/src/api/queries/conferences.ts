import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

/** main proceedings, Findings, or journal papers (TACL, CL) */
export type ConfKind = 'main' | 'findings' | 'journal'
export const CONF_KINDS: { value: ConfKind; label: string }[] = [
  { value: 'main', label: 'Main' },
  { value: 'findings', label: 'Findings' },
  { value: 'journal', label: 'Journal' },
]

export interface ConfTopic {
  id: number
  name: string
  description: string
  position: number
}

export interface ConfVenue {
  slug: string
  name: string
  full_name: string
  journal: boolean
  years: number[]
  editions: { year: number; papers: number }[]
  latest: number | null
  latest_papers: number
  latest_kinds: Partial<Record<ConfKind, number>>
  papers: number
}

export interface ConfProgress {
  papers: number
  sorted: number
  cited: number
  abstracts: number
}

export interface ConfStatus {
  stage?: 'queued' | 'importing' | 'terms' | 'embedding' | 'sorting' | 'summaries' | 'paused' | 'waiting' | 'idle'
  error?: string | null
  last_sync?: string
  updated_at?: string
}

export interface ConferenceList {
  family: { slug: 'all'; name: string; editions: { year: number; papers: number }[] }
  venues: ConfVenue[]
  topics: ConfTopic[]
  progress: ConfProgress
  status: ConfStatus
}

export interface ConfPaperBrief {
  id: string
  title: string
  year: number
  authors: string[]
  author_count: number
  awards: string[]
  award_rank: number | null
  citation_count: number | null
  kind: ConfKind | null
  topic: { id: number; name: string } | null
  url: string
  pdf_url: string
  item_id: string | null
}

export interface ConfTopicShare {
  id: number
  name: string
  papers: number
  share: number
  prev_papers: number | null
  prev_share: number | null
  /** share minus the previous edition's, as a fraction */
  change: number | null
}

export interface ConfTerm {
  term: string
  papers: number
  share: number
  prev_share: number
  score: number
}

export interface ConfEdition {
  venue: string
  name: string
  year: number
  previous_year: number | null
  kinds: ConfKind[]
  years: { year: number; papers: number }[]
  papers: number
  by_kind: Partial<Record<ConfKind, number>>
  topics: ConfTopicShare[]
  awards: ConfPaperBrief[]
  terms: { rising: ConfTerm[]; falling: ConfTerm[] }
  summary: { text: string; written_at: string; model: string | null } | null
  progress: ConfProgress
}

export interface ConfTrendYear {
  year: number
  papers: number
  sorted: number
  /** papers per topic id */
  topics: Record<string, number>
}

export interface ConfTrends {
  venue: string
  name: string
  topics: ConfTopic[]
  years: ConfTrendYear[]
}

export interface ConfCompare {
  year: number
  topics: ConfTopic[]
  venues: { venue: string; name: string; papers: number; sorted: number; topics: Record<string, number> }[]
  missing: string[]
}

export interface ConfPaperPage {
  name: string
  papers: ConfPaperBrief[]
  total: number
  offset: number
  topic: { id: number; name: string | null } | null
}

export interface ConfPaper extends ConfPaperBrief {
  abstract: string | null
  abstract_from: 'anthology' | 'openalex' | 'semantic_scholar' | null
  doi: string | null
  volume: { id: string; title: string | null }
  venues: { slug: string; name: string }[]
  topic_score: number | null
  citations_at: string | null
  similar: ConfPaperBrief[]
}

const kindsParam = (kinds: ConfKind[]) => (kinds.length === CONF_KINDS.length ? undefined : kinds.join(','))
const STALE = 5 * 60 * 1000

/** The venues with their editions, the topic list, and how far the pipeline has got */
export const useConferences = () =>
  useQuery({
    queryKey: ['conferences'],
    queryFn: async () => (await apiClient.get<ConferenceList>('/conferences')).data,
    staleTime: 60 * 1000,
  })

/** One edition (the latest without a year): topic shares, awards, terms and summary */
export const useEdition = (venue: string, year: number | null, kinds: ConfKind[]) =>
  useQuery({
    queryKey: ['conferences', 'edition', venue, year, kinds],
    queryFn: async () => (await apiClient.get<ConfEdition>(`/conferences/${venue}`, {
      params: { year: year ?? undefined, kinds: kindsParam(kinds) } })).data,
    placeholderData: keepPreviousData,
    staleTime: STALE,
  })

export const useConfTrends = (venue: string, kinds: ConfKind[]) =>
  useQuery({
    queryKey: ['conferences', 'trends', venue, kinds],
    queryFn: async () => (await apiClient.get<ConfTrends>(`/conferences/${venue}/trends`, {
      params: { kinds: kindsParam(kinds) } })).data,
    placeholderData: keepPreviousData,
    staleTime: STALE,
  })

export const useConfCompare = (venues: string[], year: number | null, kinds: ConfKind[]) =>
  useQuery({
    queryKey: ['conferences', 'compare', venues, year, kinds],
    queryFn: async () => (await apiClient.get<ConfCompare>('/conferences/compare', {
      params: { venues: venues.join(','), year, kinds: kindsParam(kinds) } })).data,
    enabled: venues.length > 0 && year !== null,
    placeholderData: keepPreviousData,
    staleTime: STALE,
  })

export const useConfPapers = (venue: string, opts: { year: number | null; topic: number | null; kinds: ConfKind[]; offset: number; limit?: number; awards?: boolean }) =>
  useQuery({
    queryKey: ['conferences', 'papers', venue, opts],
    queryFn: async () => (await apiClient.get<ConfPaperPage>(`/conferences/${venue}/papers`, {
      params: { year: opts.year ?? undefined, topic: opts.topic ?? undefined, kinds: kindsParam(opts.kinds),
        offset: opts.offset, limit: opts.limit ?? 20, awards: opts.awards || undefined } })).data,
    placeholderData: keepPreviousData,
    staleTime: STALE,
  })

export const useConfPaper = (id: string | null) =>
  useQuery({
    queryKey: ['conferences', 'paper', id],
    queryFn: async () => (await apiClient.get<ConfPaper>(`/conferences/papers/${id}`)).data,
    enabled: !!id,
    staleTime: STALE,
  })

/** The paper as a feed item, made if it has none, so it can be saved, noted and added to projects */
export const useConfPaperItem = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) =>
      (await apiClient.post<{ item_id: string; made: boolean }>(`/conferences/papers/${id}/item`)).data,
    onSuccess: (_d, id) => qc.invalidateQueries({ queryKey: ['conferences', 'paper', id] }),
  })
}

// ── admin ────────────────────────────────────────────────────────────

const useInvalidate = () => {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: ['conferences'] })
}

export const useAddConfTopic = () => {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async (body: { name: string; description: string }) =>
      (await apiClient.post<ConfTopic>('/conferences/topics', body)).data,
    onSuccess: invalidate,
  })
}

export const useEditConfTopic = () => {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: number; name?: string; description?: string; position?: number }) =>
      (await apiClient.patch<ConfTopic>(`/conferences/topics/${id}`, body)).data,
    onSuccess: invalidate,
  })
}

export const useDeleteConfTopic = () => {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async (id: number) => { await apiClient.delete(`/conferences/topics/${id}`) },
    onSuccess: invalidate,
  })
}

export const useSyncConferences = () => {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: async () => (await apiClient.post<{ queued: boolean }>('/conferences/sync')).data,
    onSuccess: invalidate,
  })
}
