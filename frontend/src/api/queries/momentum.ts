import { useQuery } from '@tanstack/react-query'
import { apiClient, type FeedItem } from '../client'

export interface MomentumPoint {
  date: string
  citations: number
  /** Rebuilt from the dates of the papers citing it, not read on that day */
  rebuilt: boolean
}

export interface ItemMomentum {
  total: number
  fetched_at: string | null
  gain_7d: number | null
  gain_30d: number | null
  series: MomentumPoint[]
}

/** A feed paper's citations, one point a day for the last 90 days (Semantic Scholar, refreshed daily). */
export const useItemMomentum = (itemId: string, enabled = true) =>
  useQuery({
    queryKey: ['momentum', itemId],
    queryFn: async () => (await apiClient.get<ItemMomentum>(`/items/${itemId}/momentum`)).data,
    enabled,
    staleTime: 30 * 60 * 1000,
  })

export type RisingWindow = '7d' | '30d'

export interface RisingItem extends FeedItem {
  gain: number
  /** Citations per day over the window's sparkline span */
  series: number[]
}

/** Feed papers gaining the most citations over the last 7 or 30 days. */
export const useRising = (window: RisingWindow, limit = 10) =>
  useQuery({
    queryKey: ['rising', window, limit],
    queryFn: async () => (await apiClient.get<{ window: RisingWindow; items: RisingItem[] }>('/momentum/rising', { params: { window, limit } })).data.items,
    staleTime: 10 * 60 * 1000,
  })
