/** Idea checks against every map, and questions to one map. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { type GapTheme } from './gaps'

export interface IdeaPaper {
  id: string
  title: string
  year: number | null
  authors: string[]
  abstract: string
  url: string
  score: number
  maps: { topic: string; topic_name: string; milestone: boolean }[]
}

export interface IdeaTheme {
  id: string
  label: string
  status: GapTheme['status']
  open: boolean
  topic: string
  topic_name: string
  size: number
  first_year: number | null
  last_year: number | null
  score: number
  hits: number
  example: { sentence: string; paper: { id: string; title: string; year: number | null } | null; stated_by: { id: string; title: string; year: number | null } | null }
  fixed_by: { id: string; title: string; year: number | null }[]
  maybe_addressed_by: { id: string; title: string | null; score: number }[]
}

export interface IdeaCheckResult {
  papers: IdeaPaper[]
  themes: IdeaTheme[]
  unthemed_gaps: { sentence: string; score: number; paper: { id: string; title: string; year: number | null } | null }[]
  verdict: { closest: string; new: string; gaps?: string } | null
  verdict_error?: string
}

export interface IdeaCheckSummary {
  id: string
  idea: string
  created_at: string
  papers: number
  themes: number
  open_themes: number
}

export interface IdeaCheck extends IdeaCheckSummary {
  result: IdeaCheckResult
}

export const useIdeaChecks = () =>
  useQuery({
    queryKey: ['evolution', 'idea-checks'],
    queryFn: async () => (await apiClient.get<IdeaCheckSummary[]>('/evolution/idea-checks')).data,
  })

export const useIdeaCheck = (id: string | null) =>
  useQuery({
    queryKey: ['evolution', 'idea-check', id],
    queryFn: async () => (await apiClient.get<IdeaCheck>(`/evolution/idea-checks/${id}`)).data,
    enabled: !!id,
    staleTime: Infinity,
  })

export const useCreateIdeaCheck = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { idea: string; verdict: boolean }) =>
      (await apiClient.post<IdeaCheck>('/evolution/idea-checks', vars, { timeout: 180_000 })).data,
    onSuccess: (check) => {
      queryClient.setQueryData(['evolution', 'idea-check', check.id], check)
      queryClient.invalidateQueries({ queryKey: ['evolution', 'idea-checks'] })
    },
  })
}

export const useDeleteIdeaCheck = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/evolution/idea-checks/${id}`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'idea-checks'] }),
  })
}

export type SectionFilter = 'method' | 'results' | 'limitations'

export interface MapSource {
  n: number
  paper_id: string
  title: string
  year: number | null
  named_method: string | null
  section_type: string
  heading: string
  abstract_only: boolean
  score: number
  excerpt: string
}

export interface MapQuestion {
  id: string
  question: string
  answer: string
  sources: MapSource[]
  sections: SectionFilter[]
  created_at: string
}

export const useMapQuestions = (slug: string) =>
  useQuery({
    queryKey: ['evolution', 'questions', slug],
    queryFn: async () => (await apiClient.get<MapQuestion[]>(`/evolution/topics/${slug}/questions`)).data,
  })

export const useClearMapQuestions = (slug: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/evolution/topics/${slug}/questions`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'questions', slug] }),
  })
}
