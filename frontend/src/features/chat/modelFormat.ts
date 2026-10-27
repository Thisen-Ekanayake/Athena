import type { Device, ModelContext } from '../../api/queries/chats'
import type { Placement } from '../../api/queries/modelRegistry'

/** 8192 -> "8k" */
export const tokens = (n: number) => (n >= 1000 ? `${Math.round(n / 1024) || Math.round(n / 1000)}k` : String(n))

export const bytes = (n: number | null | undefined) => {
  if (!n) return '—'
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`
  if (n >= 1e6) return `${Math.round(n / 1e6)} MB`
  return `${Math.round(n / 1e3)} kB`
}

export const megabytes = (mb: number) => (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`)

export const DEVICE_LABEL: Record<Device, string> = { gpu: 'GPU', split: 'GPU + CPU', cpu: 'CPU' }

/** "GPU", "GPU + CPU · 28/33 layers on GPU", "CPU" */
export function deviceText(c: Pick<ModelContext, 'device' | 'gpu_layers' | 'layers'>, long = false) {
  if (c.device === 'split') return long ? `GPU + CPU · ${c.gpu_layers}/${c.layers} layers on GPU` : `GPU + CPU ${c.gpu_layers}/${c.layers}`
  return DEVICE_LABEL[c.device]
}

/** "38 tok/s" when measured, "~38 tok/s" when estimated */
export function speedText(c: Pick<ModelContext, 'tps' | 'speed_source'>) {
  if (!c.tps) return '—'
  const n = c.tps >= 10 ? Math.round(c.tps) : Math.round(c.tps * 10) / 10
  return `${c.speed_source === 'measured' ? '' : '~'}${n} tok/s`
}

/** What a context size is good for */
export function contextHint(n: number) {
  if (n <= 8192) return 'Short chats · fastest'
  if (n <= 16384) return 'A paper and the conversation'
  if (n <= 32768) return 'Long PDFs or several papers'
  return 'Very long documents'
}

export const seconds = (s: number) => (s < 10 ? `${s.toFixed(1)} s` : `${Math.round(s)} s`)

/** Where a registered model loads, as the admin picks it */
export const PLACEMENTS: { value: Placement; label: string; title: string }[] = [
  { value: 'auto', label: 'Auto', title: 'llama.cpp puts as many layers on the GPU as fit, the rest on the CPU' },
  { value: 'gpu', label: 'GPU', title: 'Every layer on the GPU, even if it is tight' },
  { value: 'cpu', label: 'CPU', title: 'All on the CPU: slower, but it stays loaded beside the GPU model' },
]
