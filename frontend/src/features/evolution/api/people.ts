/** Key people per era, and who introduced each milestone. */
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { useMapScope } from './scope'
import { type EvolutionTopic } from './topics'

export interface PersonPaper {
  id: string
  title: string
  year: number | null
  named_method: string | null
  is_milestone: boolean
}

export interface RankedAuthor {
  id: string | null
  name: string
  papers: number
  milestones: number
  weight: number
  best_paper: PersonPaper
}

export interface RankedLab extends RankedAuthor {
  country: string | null
}

export interface PeopleEra {
  start: number
  end: number
  papers: number
  authors: RankedAuthor[]
  labs: RankedLab[]
}

export interface TopicPeople {
  topic: EvolutionTopic
  eras: PeopleEra[]
  overall: { authors: RankedAuthor[]; labs: RankedLab[] }
  milestones: (PersonPaper & { authors: { id: string | null; name: string; institutions: string[] }[] })[]
  papers: number
  papers_with_ids: number
}

export const useTopicPeople = (slug: string) => {
  const scope = useMapScope()
  return useQuery({
    queryKey: [scope.key, 'people', slug],
    queryFn: async () => (await apiClient.get<TopicPeople>(`${scope.base(slug)}/people`)).data,
    staleTime: 5 * 60 * 1000,
  })
}
