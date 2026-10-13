import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

export interface InboxEvent {
  id: string
  kind: 'map_changes' | 'map_new' | 'feed_citations'
  title: string
  body: string | null
  link: string | null
  created_at: string
  unread: boolean
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
