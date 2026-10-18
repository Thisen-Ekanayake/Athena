/** Gap themes and the gaps behind them. */
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { type EvolutionNode } from './graph'
import { ACCOUNT_SCOPE, type MapScope, useMapScope } from './scope'
import { type EvolutionTopic } from './topics'

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

export const topicGapsQuery = (slug: string | undefined, scope: MapScope = ACCOUNT_SCOPE) => ({
  queryKey: [scope.key, 'gaps', slug],
  queryFn: async () => (await apiClient.get<TopicGaps>(`${scope.base(slug!)}/gaps`)).data,
  enabled: !!slug,
  staleTime: 5 * 60 * 1000,
})

export const useTopicGaps = (slug: string | undefined) => useQuery(topicGapsQuery(slug, useMapScope()))
