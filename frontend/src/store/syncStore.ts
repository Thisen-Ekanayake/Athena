import { create } from 'zustand'

const DISMISSED_KEY = 'athena:sync-dismissed'

function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISSED_KEY)
  } catch {
    return null
  }
}

interface SyncUiState {
  /** The sync dialog (progress and log) is open */
  dialogOpen: boolean
  openDialog: () => void
  closeDialog: () => void
  /** The finished sync whose result the sidebar no longer shows; kept across reloads */
  dismissedId: string | null
  dismiss: (id: string) => void
}

export const useSyncUi = create<SyncUiState>((set) => ({
  dialogOpen: false,
  openDialog: () => set({ dialogOpen: true }),
  closeDialog: () => set({ dialogOpen: false }),
  dismissedId: readDismissed(),
  dismiss: (id) => {
    try {
      localStorage.setItem(DISMISSED_KEY, id)
    } catch {
      // Private windows: dismissed for this session only
    }
    set({ dismissedId: id })
  },
}))
