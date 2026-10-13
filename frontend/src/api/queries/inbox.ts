import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

export type InboxKind = 'map_changes' | 'map_new' | 'feed_citations' | 'watch_matches' | 'digest' | 'budget'

/** A feed item an entry points at; similarity is set for searches. */
export interface InboxItem {
  id: string
  title: string
  score?: number | null
  similarity?: number | null
  cites?: string[]
}

export interface DigestPayload {
  frequency: 'daily' | 'weekly'
  period: { start: string; end: string }
  watches: { watch_id: string; kind: WatchKind; label: string; link: string | null; count: number; items: InboxItem[] }[]
  maps: { name: string; slug: string; changes: string[]; reason: string; taken_at: string }[]
  new_maps: { title: string; link: string | null; body: string | null }[]
  citations: { title: string; link: string | null; items: InboxItem[] }[]
  new_items: number
  top_papers: InboxItem[]
  briefs: { category: string; theme: string; brief: string; generated_at: string }[]
}

export interface InboxEvent {
  id: string
  kind: InboxKind
  title: string
  body: string | null
  link: string | null
  created_at: string
  unread: boolean
  payload: { items?: InboxItem[]; label?: string; watch_kind?: WatchKind } & Partial<DigestPayload>
}

export const useInboxUnread = () =>
  useQuery({
    queryKey: ['inbox', 'unread'],
    queryFn: async () => (await apiClient.get<{ unread: number }>('/inbox/unread')).data.unread,
    refetchInterval: 60_000,
  })

export const useInbox = (enabled: boolean, limit = 30) =>
  useQuery({
    queryKey: ['inbox', 'events', limit],
    queryFn: async () => (await apiClient.get<{ events: InboxEvent[]; unread: number }>('/inbox', { params: { limit } })).data,
    enabled,
  })

export const useMarkInboxSeen = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      await apiClient.post('/inbox/seen')
    },
    onSuccess: () => queryClient.setQueryData(['inbox', 'unread'], 0),
  })
}

/* ── Follows ── */

export type WatchKind = 'map' | 'search' | 'source' | 'cluster'
export type Delivery = 'instant' | 'digest'

export interface Watch {
  id: string
  kind: WatchKind
  target: string
  /** The followed map, source or cluster id, or the search's query */
  ref: string
  delivery: Delivery
  label: string
  link: string | null
  /** retired: re-clustering dropped the cluster */
  status: 'active' | 'retired'
  hits_7d: number
  created_at: string | null
}

export type FollowTarget =
  | { kind: 'map'; topic_id: string }
  | { kind: 'source'; source_id: string }
  | { kind: 'cluster'; cluster_id: string }
  | { kind: 'search'; query: string }

/** The key the API gives a watch, so a page can tell whether it is followed. */
export function targetKey(t: FollowTarget): string {
  switch (t.kind) {
    case 'map': return `map:${t.topic_id}`
    case 'source': return `source:${t.source_id}`
    case 'cluster': return `cluster:${t.cluster_id}`
    case 'search': return `search:${t.query.split(/\s+/).filter(Boolean).join(' ').toLowerCase()}`
  }
}

export const useWatches = () =>
  useQuery({
    queryKey: ['watches'],
    queryFn: async () => (await apiClient.get<{ watches: Watch[]; limit: number }>('/watches')).data,
    staleTime: 60_000,
  })

function useWatchMutation<T>(fn: (arg: T) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watches'] })
      queryClient.invalidateQueries({ queryKey: ['inbox'] })
    },
  })
}

export const useFollow = () =>
  useWatchMutation((target: FollowTarget & { delivery?: Delivery }) => apiClient.post<Watch>('/watches', target))

export const useUnfollow = () => useWatchMutation((id: string) => apiClient.delete(`/watches/${id}`))

export const useSetDelivery = () =>
  useWatchMutation(({ id, delivery }: { id: string; delivery: Delivery }) => apiClient.patch(`/watches/${id}`, { delivery }))

/* ── Settings ── */

export interface InboxSettings {
  digest: 'off' | 'daily' | 'weekly'
  /** 0 = Monday */
  digest_day: number
  muted_kinds: ('map_new' | 'feed_citations')[]
  last_digest_at: string | null
  /** When digests go out, set on the server */
  digest_hour_utc: number
}

export const useInboxSettings = () =>
  useQuery({
    queryKey: ['inbox', 'settings'],
    queryFn: async () => (await apiClient.get<InboxSettings>('/inbox/settings')).data,
  })

export const useSaveInboxSettings = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (s: Pick<InboxSettings, 'digest' | 'digest_day' | 'muted_kinds'>) => (await apiClient.put<InboxSettings>('/inbox/settings', s)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(['inbox', 'settings'], data)
      queryClient.invalidateQueries({ queryKey: ['inbox', 'events'] })
      queryClient.invalidateQueries({ queryKey: ['inbox', 'unread'] })
    },
  })
}
