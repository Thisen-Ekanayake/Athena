/** The feed and the maps: a feed item's place in them, and new feed papers citing their milestones. */
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { type EvolutionNode } from './graph'
import { type EvolutionTopic } from './topics'

export interface CitedMilestone {
  topic: string
  topic_name: string
  paper_id: string
  title: string
  year: number | null
  named_method: string | null
}

export interface FeedPlace {
  topic: EvolutionTopic
  paper_id: string
  kind: EvolutionNode['kind']
  year: number | null
  era: [number, number] | null
  is_milestone: boolean
  on_main_path: boolean
  rank: number
  of: number
  gaps_stated: string[]
  gaps_stated_count: number
  solves: { paper_id: string; title: string | null; sentence: string }[]
  loose_matches: number
}

export interface FeedItemEvolution {
  item_id: string
  places: FeedPlace[]
  cites: CitedMilestone[]
  maps_cited: Record<string, number>
  references: number | null
  checked_at: string | null
}

export interface NewMapPaper {
  id: string
  title: string
  url: string
  published_at: string
  score: number | null
  cites: CitedMilestone[]
}

export const useFeedItemEvolution = (itemId: string) =>
  useQuery({
    queryKey: ['evolution', 'item', itemId],
    queryFn: async () => (await apiClient.get<FeedItemEvolution>(`/evolution/items/${itemId}`)).data,
    staleTime: 5 * 60 * 1000,
  })

export const useNewMapPapers = (topic?: string, days = 30) =>
  useQuery({
    queryKey: ['evolution', 'new-papers', topic ?? 'all', days],
    queryFn: async () =>
      (await apiClient.get<NewMapPaper[]>('/evolution/new-papers', { params: { days, topic } })).data,
    staleTime: 5 * 60 * 1000,
  })
