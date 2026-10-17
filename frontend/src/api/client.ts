import axios from 'axios'
import { queryClient } from './queryClient'

/** Base URL of the v1 API, shared by axios and the streaming endpoints (Q&A, sync events). The API is on the
 *  app's own origin (nginx in the image, Vite's proxy in development); VITE_API_URL points it elsewhere, which
 *  then needs that origin in the API's CORS_ORIGINS. */
export const API_BASE: string = import.meta.env.VITE_API_URL || '/api/v1'

// Create a configured axios instance. The session lives in an httpOnly cookie, so requests carry credentials.
export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

// A 401 means the session ended (logged out elsewhere, deactivated, expired); a 403 with this detail means a
// temporary password must be replaced. Either way, re-read who is logged in and let the route guard redirect.
apiClient.interceptors.response.use(undefined, (error) => {
  const status = error?.response?.status
  const detail = error?.response?.data?.detail
  if (status === 401 || (status === 403 && detail === 'password_change_required')) {
    if (!String(error?.config?.url ?? '').startsWith('/auth/')) {
      queryClient.invalidateQueries({ queryKey: ['auth'] })
    }
  }
  return Promise.reject(error)
})

// Types for the API responses
export interface Source {
  id: string
  name: string
  url: string
  type: string
  category: string
  authority_score: number
  is_active: boolean
  added_by: string
  last_fetched_at?: string
  created_at?: string
  consecutive_failures: number
}

export interface ClusterInfo {
  id: string
  label: string
  summary: string
  item_count: number
  is_active: boolean
}

/** A content item as the feed, search, cluster and list endpoints return it (`_build_feed_item`). */
export interface FeedItem {
  id: string
  title: string
  url: string
  summary: string | null
  summary_status?: string
  score: number
  published_at: string
  category: string
  is_trending: boolean
  authors?: string[]
  citation_count?: number
  source: {
    name: string
    type: string
    authority: number
  }
  cluster?: { id: string; label: string | null } | null
  takeaways?: string[] | null
  related_count: number
  /** Milestones of the evolution maps it cites */
  milestones_cited?: number
  /** Citations gained in the last 7 days (papers; null until known) */
  citation_gain_7d?: number | null
  /** The user's own state: read, their reaction, whether they wrote notes or highlights */
  me?: ItemMeSummary | null
  /** For you only: how close it is to what the user liked, as a rank among the candidates (0-1) */
  interest?: number | null
  /** Search only: how it matched the query (exact: its title names it) */
  match?: 'exact' | 'both' | 'keyword' | 'meaning'
}

export type Reaction = 'up' | 'down' | 'hide'

export interface ItemMeSummary {
  read: boolean
  annotated: boolean
  reaction: Reaction | null
}

export interface FeedResponse {
  items: FeedItem[]
  pagination: {
    page: number
    limit: number
    total: number
    has_next: boolean
  }
  /** The For-you order was used (false: it fell back to relevance) */
  personalised?: boolean
}

export interface TrendingResponse {
  brief?: {
    theme: string
    brief: string
    generated_at: string
  }
  items: FeedItem[]
}
