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

/** How far the map's open problems have got (athena/evolution/progress.py); null before anyone asked. */
export interface GapsProgress {
  stage: 'queued' | 'reading' | 'labelling' | 'gaps' | 'embedding' | 'themes' | 'naming' | 'done'
  label: string
  done: number
  total: number | null
  started: number
  updated: number
  eta_seconds: number | null
  note: string | null // why the PDFs were not read, or that background work is paused
}

export interface TopicGaps {
  topic: EvolutionTopic
  latest_year: number | null
  themes: GapTheme[]
  loose_min_score: number
  progress?: GapsProgress | null
  waiting?: { reason: 'chat' | 'paused' | 'turn'; detail: string | null; since: number } | null
}

export const gapsInProgress = (data: TopicGaps | undefined) => !!data?.progress && data.progress.stage !== 'done'

export const topicGapsQuery = (slug: string | undefined, scope: MapScope = ACCOUNT_SCOPE) => ({
  queryKey: [scope.key, 'gaps', slug],
  queryFn: async () => (await apiClient.get<TopicGaps>(`${scope.base(slug!)}/gaps`)).data,
  enabled: !!slug,
  staleTime: 5 * 60 * 1000,
  // While the GPU works on them, look again every 15 s: the progress line moves and themes arrive at the end.
  refetchInterval: (query: { state: { data?: TopicGaps } }) => (gapsInProgress(query.state.data) ? 15_000 : false),
})

export const useTopicGaps = (slug: string | undefined) => useQuery(topicGapsQuery(slug, useMapScope()))
