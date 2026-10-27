import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type Accent = 'gold' | 'indigo'

interface AppState {
  accent: Accent
  setAccent: (accent: Accent) => void
  currentCategory: string | null
  setCategory: (category: string | null) => void
  /** The sidebar lists the projects under the Projects link */
  projectsOpen: boolean
  setProjectsOpen: (open: boolean) => void
}

/** The CSS reads the accent from <html data-accent>. Set it right away so canvases built next see the new colours. */
function applyAccent(accent: Accent) {
  document.documentElement.dataset.accent = accent
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      accent: 'gold',
      setAccent: (accent) => {
        applyAccent(accent)
        set({ accent })
      },
      currentCategory: null,
      setCategory: (category) => set({ currentCategory: category }),
      projectsOpen: false,
      setProjectsOpen: (open) => set({ projectsOpen: open }),
    }),
    {
      name: 'athena-storage',
      version: 2,
      // Earlier versions stored a light/dark theme and a view mode; keep only what still exists.
      migrate: (persisted) => {
        const old = (persisted ?? {}) as Partial<AppState>
        return { accent: old.accent ?? 'gold', currentCategory: old.currentCategory ?? null, projectsOpen: false } as AppState
      },
      onRehydrateStorage: () => (state) => {
        if (state) applyAccent(state.accent)
      },
    }
  )
)
