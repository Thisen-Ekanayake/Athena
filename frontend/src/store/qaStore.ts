import { create } from 'zustand'

export interface QAMessage {
  role: 'user' | 'assistant'
  content: string
}

interface QAState {
  // Dictionary of item_id -> conversation history
  sessions: Record<string, QAMessage[]>
  
  // Which item's QAPanel is currently open
  activeItemId: string | null
  
  // Actions
  setActiveItem: (id: string | null) => void
  addMessage: (itemId: string, msg: QAMessage) => void
  clearSession: (itemId: string) => void
  updateLastMessage: (itemId: string, content: string) => void
}

export const useQAStore = create<QAState>((set) => ({
  sessions: {},
  activeItemId: null,
  
  setActiveItem: (id) => set({ activeItemId: id }),
  
  addMessage: (itemId, msg) => set((state) => {
    const history = state.sessions[itemId] || []
    return {
      sessions: {
        ...state.sessions,
        [itemId]: [...history, msg]
      }
    }
  }),
  
  updateLastMessage: (itemId, content) => set((state) => {
    const history = state.sessions[itemId] || []
    if (history.length === 0) return state
    
    const newHistory = [...history]
    const lastIdx = newHistory.length - 1
    newHistory[lastIdx] = { ...newHistory[lastIdx], content }
    
    return {
      sessions: {
        ...state.sessions,
        [itemId]: newHistory
      }
    }
  }),
  
  clearSession: (itemId) => set((state) => {
    const newSessions = { ...state.sessions }
    delete newSessions[itemId]
    return { sessions: newSessions }
  })
}))
