import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

export type SyncState = 'idle' | 'running' | 'done' | 'partial' | 'error' | 'stalled'
export type SyncSourceState = 'queued' | 'running' | 'retrying' | 'done' | 'empty' | 'error'

export interface SyncSource {
  id: string
  name: string
  state: SyncSourceState
  new?: number | null
  error?: string | null
  /** Epoch seconds of the next attempt, while retrying */
  retry_at?: number | null
}

export interface SyncLogLine {
  seq: number
  line: string
}

/** The latest sync (GET /sync/status). Times are epoch seconds. */
export interface SyncStatus {
  state: SyncState
  id?: string
  trigger?: 'manual' | 'scheduled'
  started_at?: number
  finished_at?: number | null
  total?: number
  completed?: number
  errors?: number
  /** Sources that listed nothing */
  empty?: number
  new_items?: number
  percent?: number
  /** Null until there is enough pace to estimate */
  eta_seconds?: number | null
  /** Nothing has started: the worker is busy or not running */
  waiting_for_worker?: boolean
  sources?: SyncSource[]
  /** Admins only, when asked for */
  log?: SyncLogLine[]
}

export const isRunning = (s: SyncStatus | undefined) => s?.state === 'running'
export const isFinished = (s: SyncStatus | undefined) => !!s && ['done', 'partial', 'error', 'stalled'].includes(s.state)

/** The latest sync's progress: every 1.5 s while one runs, otherwise each minute (to notice scheduled ones). */
export const useSyncStatus = () =>
  useQuery({
    queryKey: ['sync', 'status'],
    queryFn: async () => (await apiClient.get<SyncStatus>('/sync/status')).data,
    refetchInterval: (query) => (isRunning(query.state.data) ? 1500 : 60_000),
    refetchIntervalInBackground: false,
  })

/** The log lines after ``after`` (admins), with the status they came with. */
export const fetchSyncLog = async (after: number) =>
  (await apiClient.get<SyncStatus>('/sync/status', { params: { log: true, log_after: after } })).data

/** Starts a sync of every source; a 409 means one is already running, which is shown instead. */
export const useStartSync = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async () => (await apiClient.post<SyncStatus>('/sync')).data,
    onSuccess: (status) => queryClient.setQueryData(['sync', 'status'], status),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['sync', 'status'] }),
  })
}
