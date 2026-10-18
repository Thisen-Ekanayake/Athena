/** The reading path and read ticks. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { type EvolutionNode } from './graph'
import { useMapScope } from './scope'
import { type EvolutionTopic } from './topics'

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
export const useReadingPath = (slug: string, n: number) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: scope.readOnly ? [scope.key, 'reading-path', slug, n] : readingPathKey(slug, n),
    queryFn: async () =>
      (await apiClient.get<ReadingPath>(`${scope.base(slug)}/reading-path`, { params: { n } })).data,
    placeholderData: (previous) => previous,
    refetchInterval: (query) => (query.state.data?.notes_pending ? 3000 : false),
  })
}

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
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['evolution', 'reading-path'] })
      queryClient.invalidateQueries({ queryKey: ['me'] })  // the paper panel's read mark, and a feed item's
    },
  })
}
