import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { apiClient, type FeedItem, type ItemMeSummary, type Reaction } from '../client'

// ── types ───────────────────────────────────────────────────────────

export type MeKind = 'item' | 'paper'

export interface Note {
  body: string
  updated_at: string | null
}

export interface Highlight {
  id: string
  /** abstract | summary | takeaway:<n> | passage */
  field: string
  quote: string
  comment: string | null
  context: Record<string, string | number | null>
  created_at: string | null
  /** Where it sits in the field's current text; null when that text no longer has it */
  anchor?: { start: number; end: number } | null
}

export interface Me {
  read: boolean
  read_at: string | null
  reaction?: Reaction | null
  note: Note | null
  highlights: Highlight[]
}

export interface NewHighlight {
  field: string
  quote: string
  start?: number | null
  prefix?: string | null
  suffix?: string | null
  comment?: string | null
  context?: Record<string, string | number | null>
}

const base = (kind: MeKind, id: string) => (kind === 'item' ? `/items/${id}` : `/evolution/papers/${id}`)
const meKey = (kind: MeKind, id: string) => ['me', kind, id]

// Feed-card lists hold each item's `me`; these are the caches a change to one item shows up in.
const LIST_KEYS = [['feed'], ['trending'], ['list-items'], ['search'], ['cluster'], ['rising']]

type Patch = Partial<ItemMeSummary>

/** Apply ``patch`` to one item's `me` in every cached list (infinite pages, `{items}` payloads or arrays). */
function patchLists(qc: QueryClient, itemId: string, patch: Patch) {
  const fix = (item: FeedItem): FeedItem =>
    item.id === itemId ? { ...item, me: { read: false, annotated: false, reaction: null, ...item.me, ...patch } } : item
  const walk = (data: unknown): unknown => {
    if (Array.isArray(data)) return data.map((x) => (x && typeof x === 'object' && 'id' in x ? fix(x as FeedItem) : x))
    if (data && typeof data === 'object') {
      const d = data as { items?: unknown; pages?: unknown[] }
      if (Array.isArray(d.pages)) return { ...d, pages: d.pages.map(walk) }
      if (Array.isArray(d.items)) return { ...d, items: walk(d.items) }
    }
    return data
  }
  for (const key of LIST_KEYS) qc.setQueriesData({ queryKey: key }, walk)
}

// ── one paper's own state ───────────────────────────────────────────

export const useMe = (kind: MeKind, id: string | null | undefined, enabled = true) =>
  useQuery({
    queryKey: meKey(kind, id ?? ''),
    queryFn: async () => (await apiClient.get<Me>(`${base(kind, id!)}/me`)).data,
    enabled: !!id && enabled,
  })

/** Mark a feed item or a map paper read or unread. A feed item and the map paper that is the same paper move together. */
export const useSetRead = (kind: MeKind) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, read }: { id: string; read: boolean }) => {
      const url = `${base(kind, id)}/read`
      await (read ? apiClient.put(url) : apiClient.delete(url))
    },
    onMutate: ({ id, read }) => {
      if (kind === 'item') patchLists(qc, id, { read })
      qc.setQueryData<Me>(meKey(kind, id), (me) => (me ? { ...me, read } : me))
    },
    onSettled: (_d, _e, { id }) => {
      qc.invalidateQueries({ queryKey: meKey(kind, id) })
      qc.invalidateQueries({ queryKey: ['me'] })
      qc.invalidateQueries({ queryKey: ['lists'] })
      qc.invalidateQueries({ queryKey: ['library'] })
      qc.invalidateQueries({ queryKey: ['evolution', 'reading-path'] })
    },
  })
}

/** 👍, 👎 or "not interested" on a feed item; null takes it back. */
export const useReaction = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, reaction }: { id: string; reaction: Reaction | null }) => {
      if (reaction) await apiClient.put(`/items/${id}/feedback`, { reaction })
      else await apiClient.delete(`/items/${id}/feedback`)
    },
    onMutate: ({ id, reaction }) => {
      patchLists(qc, id, { reaction })
      qc.setQueryData<Me>(meKey('item', id), (me) => (me ? { ...me, reaction } : me))
    },
    onSettled: (_d, _e, { id }) => {
      qc.invalidateQueries({ queryKey: meKey('item', id) })
      qc.invalidateQueries({ queryKey: ['interests'] })
      qc.invalidateQueries({ queryKey: ['score-breakdown', id] })
    },
  })
}

export const useSaveNote = (kind: MeKind, id: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: string) =>
      (await apiClient.put<{ note: Note | null }>(`${base(kind, id)}/note`, { body })).data.note,
    onSuccess: (note) => {
      qc.setQueryData<Me>(meKey(kind, id), (me) => (me ? { ...me, note } : me))
      qc.invalidateQueries({ queryKey: ['library'] })
      if (kind === 'item') patchLists(qc, id, { annotated: true })
    },
  })
}

export const useAddHighlight = (kind: MeKind, id: string) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (h: NewHighlight) => (await apiClient.post<Highlight>(`${base(kind, id)}/highlights`, h)).data,
    onSuccess: (h) => {
      qc.setQueryData<Me>(meKey(kind, id), (me) => (me ? { ...me, highlights: [...me.highlights, h] } : me))
      qc.invalidateQueries({ queryKey: ['library'] })
      if (kind === 'item') patchLists(qc, id, { annotated: true })
    },
  })
}

export const useUpdateHighlight = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, comment }: { id: string; comment: string | null }) =>
      (await apiClient.patch<Highlight>(`/highlights/${id}`, { comment })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me'] })
      qc.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

export const useDeleteHighlight = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/highlights/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['me'] })
      qc.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

// ── library ─────────────────────────────────────────────────────────

export interface AboutPaper {
  kind: MeKind
  id: string
  title: string
  url?: string
  source?: string | null
  category?: string
  published_at?: string | null
  year?: number | null
  map?: { slug: string; name: string } | null
}

export interface LibraryEntry {
  about: AboutPaper
  note: Note | null
  highlights: Highlight[]
  updated_at: string | null
}

export const useLibraryNotes = (kind: 'all' | MeKind, q: string) =>
  useQuery({
    queryKey: ['library', 'notes', kind, q],
    queryFn: async () =>
      (await apiClient.get<{ entries: LibraryEntry[] }>('/library/notes', { params: { kind, q: q || undefined } })).data.entries,
  })

export interface ReadEntry {
  about: AboutPaper
  read_at: string | null
}

export const useReadHistory = () =>
  useInfiniteQuery({
    queryKey: ['library', 'read'],
    queryFn: async ({ pageParam }) =>
      (await apiClient.get<{ entries: ReadEntry[]; pagination: { page: number; has_next: boolean; total: number } }>(
        '/library/read', { params: { page: pageParam } })).data,
    initialPageParam: 1,
    getNextPageParam: (last) => (last.pagination.has_next ? last.pagination.page + 1 : undefined),
  })

// ── interests (P1) ──────────────────────────────────────────────────

export interface Interests {
  enabled: boolean
  signals: number
  full_at: number
  ready: boolean
  counts: { up: number; down: number; hide: number; saved: number }
}

export const useInterests = () =>
  useQuery({
    queryKey: ['interests'],
    queryFn: async () => (await apiClient.get<Interests>('/me/interests')).data,
    staleTime: 60 * 1000,
  })

export const useSetInterests = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (enabled: boolean) => (await apiClient.put<Interests>('/me/interests', { enabled })).data,
    onSuccess: (data) => {
      qc.setQueryData(['interests'], data)
      qc.invalidateQueries({ queryKey: ['feed'] })
    },
  })
}

export interface ReactedItem {
  id: string
  title: string
  url: string
  source: string | null
  category: string
  reacted_at: string | null
}

export const useMyFeedback = (reaction: Reaction) =>
  useQuery({
    queryKey: ['interests', 'feedback', reaction],
    queryFn: async () =>
      (await apiClient.get<{ items: ReactedItem[] }>('/me/feedback', { params: { reaction } })).data.items,
  })

export const useResetFeedback = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => (await apiClient.delete<{ removed: number }>('/me/feedback')).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['interests'] })
      qc.invalidateQueries({ queryKey: ['feed'] })
    },
  })
}
