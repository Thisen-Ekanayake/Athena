/** Snapshots and what changed, and the admin's refresh controls. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { type GapTheme } from './gaps'
import { useMapScope } from './scope'
import { type EvolutionTopic } from './topics'

export interface ChangedTheme {
  label: string
  status: GapTheme['status']
  size: number
  first_year: number | null
  last_year: number | null
  was?: GapTheme['status']
}

export interface ChangedMilestone {
  paper_id: string
  title: string
  year: number | null
  named_method: string | null
  score: number
}

export interface MapChanges {
  new_milestones: ChangedMilestone[]
  dropped_milestones: ChangedMilestone[]
  papers_added: number
  papers_removed: number
  top_new_papers: { paper_id: string; title: string; year: number | null }[]
  new_gaps: ChangedTheme[]
  solved_gaps: ChangedTheme[]
  reopened_gaps: ChangedTheme[]
  faded_gaps: ChangedTheme[]
}

export interface MapSnapshot {
  id: string
  taken_at: string
  reason: 'baseline' | 'build' | 'refresh' | 'full_text'
  built_at: string | null
  stats: { papers: number; milestones: number; themes: number; open_themes: number }
  changes: MapChanges | null
}

export interface TopicChanges {
  topic: EvolutionTopic
  refresh_days: number
  snapshots: MapSnapshot[]
}

export const useTopicChanges = (slug: string) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: [scope.key, 'changes', slug],
    queryFn: async () => (await apiClient.get<TopicChanges>(`${scope.base(slug)}/changes`)).data,
  })
}

const useTopicAction = (slug: string, path: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await apiClient.post<{ queued: boolean; task_id: string }>(`/evolution/topics/${slug}/${path}`)).data,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['evolution', 'status', slug] })
      queryClient.invalidateQueries({ queryKey: ['evolution', 'topics'] })
    },
  })
}

export const useRefreshTopic = (slug: string) => useTopicAction(slug, 'refresh')

export const useReadFullText = (slug: string) => useTopicAction(slug, 'full-text')

export const useTopicSettings = (slug: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (settings: { refresh_days?: number }) =>
      (await apiClient.patch<{ refresh_days: number }>(`/evolution/topics/${slug}/settings`, settings)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'changes', slug] }),
  })
}
