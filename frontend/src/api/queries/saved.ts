import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { FeedItem } from '../client'

export interface SavedList {
  id: string
  name: string
  item_count: number
  created_at?: string
  // Only present when lists are fetched in the context of a specific item.
  contains_item?: boolean | null
}

/** All saved lists. Pass an itemId to also learn which lists contain that item. */
export const useLists = (itemId?: string, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['lists', itemId ?? null],
    queryFn: async () => {
      const { data } = await apiClient.get<SavedList[]>('/lists', {
        params: itemId ? { item_id: itemId } : undefined,
      })
      return data
    },
    enabled,
  })
}

/** Content items saved in a list, as feed cards. */
export const useListItems = (listId: string | null) => {
  return useQuery({
    queryKey: ['list-items', listId],
    queryFn: async () => {
      const { data } = await apiClient.get<{ items: FeedItem[] }>(`/lists/${listId}/items`)
      return data.items
    },
    enabled: !!listId,
  })
}

export const useCreateList = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      const { data } = await apiClient.post<SavedList>('/lists', { name })
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['lists'] }),
  })
}

export const useRenameList = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, name }: { id: string; name: string }) => {
      const { data } = await apiClient.patch<SavedList>(`/lists/${id}`, { name })
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['lists'] }),
  })
}

export const useDeleteList = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/lists/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['lists'] }),
  })
}

export const useAddToList = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ listId, itemId }: { listId: string; itemId: string }) => {
      await apiClient.post(`/lists/${listId}/items`, { item_id: itemId })
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['lists'] })
      qc.invalidateQueries({ queryKey: ['list-items', vars.listId] })
    },
  })
}

export const useRemoveFromList = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ listId, itemId }: { listId: string; itemId: string }) => {
      await apiClient.delete(`/lists/${listId}/items/${itemId}`)
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['lists'] })
      qc.invalidateQueries({ queryKey: ['list-items', vars.listId] })
    },
  })
}
