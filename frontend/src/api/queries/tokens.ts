/** Access tokens for agents: an MCP client (Claude Code and others) uses Athena at /mcp in your account's name. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

export interface AccessToken {
  id: string
  name: string
  /** The token's first characters, to tell tokens apart */
  hint: string
  created_at: string | null
  last_used_at: string | null
  expires_at: string | null
}

/** A token just made: the only time its value is sent. */
export interface NewAccessToken extends AccessToken {
  token: string
}

const KEY = ['access-tokens']

export const useAccessTokens = () =>
  useQuery({ queryKey: KEY, queryFn: async () => (await apiClient.get<AccessToken[]>('/tokens')).data })

export const useCreateAccessToken = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: { name: string; expires_days: number | null }) =>
      (await apiClient.post<NewAccessToken>('/tokens', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}

export const useRevokeAccessToken = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/tokens/${id}`)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY }),
  })
}
