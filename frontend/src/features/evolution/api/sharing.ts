/** Share links to maps. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../../api/client'
import { timeAgo } from '../../../components/items/format'

export interface MapShare {
  id: string
  token: string
  created_by: string | null
  creator: string | null
  created_at: string | null
  /** None: until revoked */
  expires_at: string | null
  views: number
  last_viewed_at: string | null
  /** Only in the list of every map's links */
  topic?: { slug: string; name: string }
}

/** "expires in 29 days", "never expires". */
export const shareExpiry = (share: MapShare) => (share.expires_at ? `expires ${timeAgo(share.expires_at)}` : 'never expires')

/** The page's own address for a link: the app serves /share/<token> without a login. */
export const shareUrl = (token: string) => `${window.location.origin}/share/${token}`

export const useSharing = () =>
  useQuery({
    queryKey: ['evolution', 'sharing'],
    queryFn: async () => (await apiClient.get<{ enabled: boolean }>('/evolution/sharing')).data.enabled,
    staleTime: 5 * 60 * 1000,
  })

export const useSetSharing = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (enabled: boolean) => (await apiClient.put<{ enabled: boolean }>('/evolution/sharing', { enabled })).data.enabled,
    onSuccess: (enabled) => {
      queryClient.setQueryData(['evolution', 'sharing'], enabled)
      queryClient.invalidateQueries({ queryKey: ['evolution', 'shares'] })
    },
  })
}

/** The active links to one map (``slug``) or to every map: the viewer's own, or everyone's for an admin. */
export const useShares = (slug?: string, enabled = true) =>
  useQuery({
    queryKey: ['evolution', 'shares', slug ?? '*'],
    queryFn: async () =>
      (await apiClient.get<{ enabled: boolean; shares: MapShare[] }>(slug ? `/evolution/topics/${slug}/shares` : '/evolution/shares')).data,
    enabled,
  })

export const useCreateShare = (slug: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (expiresDays: number | null) =>
      (await apiClient.post<MapShare>(`/evolution/topics/${slug}/shares`, { expires_days: expiresDays })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'shares'] }),
  })
}

export const useRevokeShare = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/evolution/shares/${id}`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evolution', 'shares'] }),
  })
}

/** Opening a shared link counts one view, once per page load. */
export const countShareView = (token: string) => apiClient.post(`/share/${token}/view`).catch(() => undefined)
