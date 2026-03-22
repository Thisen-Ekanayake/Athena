import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AppState {
  theme: 'dark' | 'light'
  setTheme: (theme: 'dark' | 'light') => void
  viewMode: 'compact' | 'expanded'
  setViewMode: (mode: 'compact' | 'expanded') => void
  currentCategory: string | null
  setCategory: (category: string | null) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      theme: 'dark',
      setTheme: (theme) => set({ theme }),
      viewMode: 'expanded',
      setViewMode: (mode) => set({ viewMode: mode }),
      currentCategory: null,
      setCategory: (category) => set({ currentCategory: category }),
    }),
    {
      name: 'athena-storage',
    }
  )
)
