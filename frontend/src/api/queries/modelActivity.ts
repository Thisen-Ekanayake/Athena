import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'
import type { Device } from './chats'
import type { GpuInfo } from './modelRegistry'

/** One llama-server slot of a loaded model */
export interface Slot {
  id: number
  processing: boolean
  context: number
  prompt_tokens: number
  prompt_done: number
  prompt_cached: number
  decoded: number
  max_tokens: number | null
  /** Prompt plus answer so far: what the context holds */
  in_context: number
  /** Answer tokens a second since the last look; null when idle or on the first look */
  tps: number | null
}

export interface LoadedModel {
  preset: string
  model: string
  status: 'loaded' | 'loading'
  context: number | null
  vision: boolean
  device: Device | null
  gpu_layers: number | null
  layers: number | null
  vram_mb: number | null
  ram_mb: number | null
  slots: Slot[]
}

export interface ActivityServer {
  server: 'gpu' | 'cpu'
  url: string
  online: boolean
  models: LoadedModel[]
}

/** A model call, running or done. Only sizes and times: no prompt or answer text is kept. */
export interface ModelCall {
  id: string
  feature: string
  label: string
  model: string
  kind: 'chat' | 'embed'
  user_id: string | null
  user: string | null
  /** Work a pause holds (summaries, cluster labels, embeddings, the maps' lane) */
  background: boolean
  started: number
  server: 'gpu' | 'cpu' | null
  /** Its router held another model, which it swapped out first */
  swapped: boolean
  elapsed?: number
  seconds?: number
  status?: 'done' | 'failed' | 'stopped'
  error?: string | null
  input_tokens?: number
  output_tokens?: number
}

export interface Swap {
  at: number
  server: 'gpu' | 'cpu'
  before: string | null
  after: string | null
  cause: string
  cause_label: string
  seconds: number | null
}

export interface FeatureToday {
  feature: string
  label: string
  calls: number
  failed: number
  input_tokens: number
  output_tokens: number
  seconds: number
}

export interface Activity {
  servers: ActivityServer[]
  gpu: GpuInfo | null
  calls: ModelCall[]
  lane: {
    /** "chat", "benchmark", or a preset being loaded for a chat */
    holder: string | null
    paused: { by: string | null; since: number } | null
    waiting: { who: string; label: string; reason: 'chat' | 'paused'; since: number }[]
  }
  queues: { label: string; count: number }[]
  recent: ModelCall[]
  swaps: Swap[]
  today: FeatureToday[]
  /** The server's clock, for "how long ago" */
  now: number
}

const KEY = ['model-activity']

/** Polled every two seconds while the page is open (and the tab visible). */
export const useModelActivity = () =>
  useQuery({
    queryKey: KEY,
    queryFn: async () => (await apiClient.get<Activity>('/models/activity')).data,
    refetchInterval: 2000,
  })

export function usePauseBackground() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (pause: boolean) => (await apiClient.post(`/models/activity/${pause ? 'pause' : 'resume'}`)).data,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEY })
      void qc.invalidateQueries({ queryKey: ['model-registry'] })
    },
  })
}
