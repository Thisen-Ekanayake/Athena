import { useEffect, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { downloadFile } from '../api/download'
import { apiErrorMessage } from '../api/error'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'

export interface DownloadOption {
  label: string
  /** What the file holds, under the label */
  hint?: string
  path: string
  params: Record<string, string>
  filename: string
}

/** An Export button with a short menu of files to download (a saved list's citations, a review). */
export function DownloadMenu({ options, label = 'Export' }: { options: DownloadOption[]; label?: string }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const run = async (o: DownloadOption) => {
    setBusy(o.label)
    setError(null)
    try {
      await downloadFile(o.path, o.params, o.filename)
      setOpen(false)
    } catch (e) {
      setError(apiErrorMessage(e, 'The download failed. Check that the API is running.'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu">
        <Download /> {label}
      </Button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-1.5 grid w-64 gap-1 rounded-xl border border-line bg-surface p-1.5 text-[13px] shadow-lg">
          {options.map((o) => (
            <button key={o.label} type="button" role="menuitem" disabled={!!busy} onClick={() => void run(o)}
              className="grid gap-0.5 rounded-lg px-2.5 py-2 text-left hover:bg-surface-2 disabled:opacity-60">
              <span className="flex items-center gap-1.5 font-medium text-fg">{busy === o.label && <Spinner className="h-3 w-3" />}{o.label}</span>
              {o.hint && <span className="text-[12px] text-fg-3">{o.hint}</span>}
            </button>
          ))}
          {error && <p className="px-2.5 pb-1.5 text-[12px] text-bad" role="alert">{error}</p>}
        </div>
      )}
    </div>
  )
}
