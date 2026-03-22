import axios from 'axios'

// Create a configured axios instance
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1',
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
  consecutive_failures: number
}

export interface ClusterInfo {
  id: string
  label: string
  summary: string
  item_count: number
  is_active: boolean
}

export interface FeedItem {
  id: string
  title: string
  url: string
  summary: string
  score: number
  published_at: string
  category: string
  is_trending: boolean
  source: {
    id: string
    name: string
    url: string
    category: string
    pinned: boolean
    muted: boolean
  }
  cluster?: ClusterInfo
  takeaways?: string[]
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
