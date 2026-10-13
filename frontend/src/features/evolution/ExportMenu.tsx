import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Download } from 'lucide-react'
import { apiClient } from '../../api/client'
import { apiErrorMessage } from '../../api/error'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { saveBlob, type GraphExporter } from './graphExport'

type DataExport = { what: 'milestones' | 'reading-path' | 'gaps'; format: 'bib' | 'ris' | 'md' | 'csv' }

const GROUPS: { title: string; items: { label: string; data: DataExport }[] }[] = [
  {
    title: 'Milestones',
    items: [
      { label: 'BibTeX', data: { what: 'milestones', format: 'bib' } },
      { label: 'RIS', data: { what: 'milestones', format: 'ris' } },
      { label: 'Markdown', data: { what: 'milestones', format: 'md' } },
    ],
  },
  {
    title: 'Reading path (10 papers)',
    items: [
      { label: 'BibTeX', data: { what: 'reading-path', format: 'bib' } },
      { label: 'RIS', data: { what: 'reading-path', format: 'ris' } },
      { label: 'Markdown', data: { what: 'reading-path', format: 'md' } },
    ],
  },
  { title: 'Open problems', items: [{ label: 'CSV, one row per statement', data: { what: 'gaps', format: 'csv' } }] },
]

interface ExportMenuProps {
  slug: string
  /** The map's exporter while it is drawn; null on the other tabs. */
  exporter: () => GraphExporter | null
}

/** Downloads: the map as an image, and the milestones, reading path and open problems as files. */
export function ExportMenu({ slug, exporter }: ExportMenuProps) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const run = async (key: string, task: () => Promise<void>) => {
    setBusy(key)
    setError(null)
    try {
      await task()
      setOpen(false)
    } catch (e) {
      setError(apiErrorMessage(e, 'The export failed. Check that the API is running.'))
    } finally {
      setBusy(null)
    }
  }

  const download = (d: DataExport) =>
    run(`${d.what}.${d.format}`, async () => {
      const resp = await apiClient.get<Blob>(`/evolution/topics/${slug}/export`, { params: d, responseType: 'blob' })
      saveBlob(resp.data, `${slug}-${d.what}.${d.format}`)
    })

  const image = (format: 'png' | 'svg') =>
    run(format, async () => {
      const ex = exporter()
      if (!ex) throw new Error('Open the lineage map first')
      saveBlob(await (format === 'png' ? ex.png() : ex.svg()), `${slug}-map.${format}`)
    })

  const mapShown = open && exporter() !== null

  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="menu">
        <Download /> Export
      </Button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-1.5 grid w-64 gap-3 rounded-xl border border-line bg-surface p-3 text-[13px] shadow-lg">
          <Group title="Map image">
            {(['png', 'svg'] as const).map((f) => (
              <Item key={f} label={f.toUpperCase()} busy={busy === f} disabled={!mapShown} onClick={() => void image(f)}
                title={mapShown ? 'The whole map, not only what is on screen' : 'Open the lineage map tab first'} />
            ))}
          </Group>
          {GROUPS.map((g) => (
            <Group key={g.title} title={g.title}>
              {g.items.map((i) => {
                const key = `${i.data.what}.${i.data.format}`
                return <Item key={key} label={i.label} busy={busy === key} onClick={() => void download(i.data)} />
              })}
            </Group>
          ))}
          {error && <p className="text-[12px] text-bad" role="alert">{error}</p>}
        </div>
      )}
    </div>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="grid gap-1">
      <p className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">{title}</p>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  )
}

function Item({ label, busy, disabled, title, onClick }: { label: string; busy: boolean; disabled?: boolean; title?: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled || busy}
      title={title}
      className={cn('inline-flex h-7 items-center gap-1.5 rounded-md border border-line px-2.5 text-[12.5px] text-fg-2 transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50')}
    >
      {busy && <Spinner className="h-3 w-3" />}
      {label}
    </button>
  )
}
