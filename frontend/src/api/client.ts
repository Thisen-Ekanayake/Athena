import axios from 'axios'

/** Base URL of the v1 API, shared by axios and the streaming endpoints (Q&A, sync events). */
export const API_BASE: string = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1'

// Create a configured axios instance
export const apiClient = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
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
}

export interface FeedResponse {
  items: FeedItem[]
  pagination: {
    page: number
    limit: number
    total: number
    has_next: boolean
  }
}

export interface TrendingResponse {
  brief?: {
    theme: string
    brief: string
    generated_at: string
  }
  items: FeedItem[]
}
