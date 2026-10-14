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
  local_count: number
  live_count: number
  query: string
}

/** Research search: your library (keywords plus meaning), Semantic Scholar and arXiv. */
export async function searchPapers(query: string, limit?: number): Promise<SearchResponse> {
  const { data } = await apiClient.post<SearchResponse>('/search', typeof limit === 'number' ? { query, limit } : { query })
  return data
}
