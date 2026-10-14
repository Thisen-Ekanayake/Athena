import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

/** Calls, tokens and cost for one row of a usage table. */
export interface UsageCounts {
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

export type FeatureUsage = UsageCounts & { feature: string; label: string }

export interface Allowance {
  action: string
  label: string
  used: number
  /** None for admins: they have no daily limits */
  limit: number | null
}

export interface MyUsage {
  month: string
  resets_at: string
  totals: UsageCounts
  features: FeatureUsage[]
  token_cap: number | null
  tokens_used: number
  role: 'admin' | 'user'
  allowances: Allowance[]
  /** The app has spent this month's budget, so this person can't start model calls */
  budget_reached: boolean
}

export interface AppUsage {
  since: string
  month: string
  resets_at: string
  totals: UsageCounts
  budget_usd: number | null
  month_spend_usd: number
  over_budget: boolean
  user_token_cap: number | null
  features: FeatureUsage[]
  models: (UsageCounts & { kind: 'chat' | 'embed'; model: string })[]
  users: (UsageCounts & { user_id: string | null; name: string; email: string | null })[]
  daily: { day: string; tokens: number; cost_usd: number }[]
}

export interface UsageSettings {
  values: Record<string, string>
  defaults: Record<string, string>
  limit_labels: Record<string, string>
}

export const useMyUsage = () =>
  useQuery({
    queryKey: ['usage', 'me'],
    queryFn: async () => (await apiClient.get<MyUsage>('/usage/me')).data,
  })

export const useAppUsage = (enabled: boolean) =>
  useQuery({
    queryKey: ['usage', 'app'],
    queryFn: async () => (await apiClient.get<AppUsage>('/usage/summary')).data,
    enabled,
  })

export const useUsageSettings = (enabled: boolean) =>
  useQuery({
    queryKey: ['usage', 'settings'],
    queryFn: async () => (await apiClient.get<UsageSettings>('/usage/settings')).data,
    enabled,
  })

export const useSaveUsageSettings = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (values: Record<string, string>) =>
      (await apiClient.put<UsageSettings>('/usage/settings', { values })).data,
    onSuccess: (data) => {
      queryClient.setQueryData(['usage', 'settings'], data)
      queryClient.invalidateQueries({ queryKey: ['usage', 'app'] })
      queryClient.invalidateQueries({ queryKey: ['usage', 'me'] })
    },
  })
}
