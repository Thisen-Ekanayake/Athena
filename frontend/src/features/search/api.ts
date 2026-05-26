import { apiClient } from '../../api/client'

export interface PaperResult {
  id: string
  title: string
  abstract: string | null
  url: string | null
  year: number | null
  authors: string[]
  citation_count: number | null
  score: number | null
  source: 'local' | 'semantic_scholar'
}

export interface SearchResponse {
  papers: PaperResult[]
  lit_review: string | null
  local_count: number
  live_count: number
  query: string
}

export interface SearchRequest {
  query: string
  limit?: number
  generate_review?: boolean
}

export async function searchPapers(
  query: string,
  limit?: number,
  generateReview?: boolean,
): Promise<SearchResponse> {
  const body: SearchRequest = { query }
  if (typeof limit === 'number') body.limit = limit
  if (typeof generateReview === 'boolean') body.generate_review = generateReview

  const { data } = await apiClient.post<SearchResponse>('/search', body)
  return data
}
