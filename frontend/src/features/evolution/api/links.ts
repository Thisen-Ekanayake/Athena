/** Links between maps: shared papers and borrowed milestones. */
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { type EvolutionTopic } from './topics'

export interface LinkPaper {
  id: string
  title: string | null
  year: number | null
  named_method: string | null
  is_milestone: boolean
}

export interface TopicLinks {
  topic: EvolutionTopic
  shared: { total: number; papers: (LinkPaper & { elsewhere: { topic: string; topic_name: string; milestone: boolean }[] })[] }
  borrowed: (LinkPaper & { from: { topic: string; topic_name: string }; citing_papers: number })[]
  lent: (LinkPaper & { citing_papers: number; by: Record<string, number> })[]
}

export const useTopicLinks = (slug: string) =>
  useQuery({
    queryKey: ['evolution', 'links', slug],
    queryFn: async () => (await apiClient.get<TopicLinks>(`/evolution/topics/${slug}/links`)).data,
    staleTime: 5 * 60 * 1000,
  })
