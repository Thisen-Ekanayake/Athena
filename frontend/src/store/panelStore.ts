import { create } from 'zustand'
import type { FeedItem } from '../api/client'

interface PanelState {
  /** The item shown in the side panel. A list row passes the item it already has, so the panel opens instantly. */
  itemId: string | null
  item: FeedItem | null
  open: (item: FeedItem | string) => void
  close: () => void
}

export const usePanelStore = create<PanelState>((set) => ({
  itemId: null,
  item: null,
  open: (item) => set(typeof item === 'string' ? { itemId: item, item: null } : { itemId: item.id, item }),
  close: () => set({ itemId: null, item: null }),
}))

interface PaletteState {
  isOpen: boolean
  query: string
  open: (query?: string) => void
  close: () => void
  setQuery: (query: string) => void
}

export const usePaletteStore = create<PaletteState>((set) => ({
  isOpen: false,
  query: '',
  open: (query) => set((s) => ({ isOpen: true, query: query ?? s.query })),
  close: () => set({ isOpen: false }),
  setQuery: (query) => set({ query }),
}))
