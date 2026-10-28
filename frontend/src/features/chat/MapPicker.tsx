import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, GitBranch, Search, Sparkles, X } from 'lucide-react'
import type { MapPick } from '../../api/queries/chats'
import { Button } from '../../ui/Button'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { isBuilding, useEvolutionTopics } from '../evolution/api/topics'

/**
 * Pick research maps to attach (built maps only), any number. Each picked map can also go to the model as a graph
 * of its milestones, lineage and open problems ("summary"); without it only the user sees the map.
 */
export function MapPicker({ onClose, onAttach, attached = [], busy, error, title = 'Attach research maps' }: {
  onClose: () => void
  onAttach: (picks: MapPick[]) => void
  /** Slugs already attached: shown, not offered again */
  attached?: string[]
  busy?: boolean
  error?: string | null
  title?: string
}) {
  const topics = useEvolutionTopics()
  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<Record<string, boolean>>({})  // slug -> share
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    dialogRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const built = useMemo(() => (topics.data ?? []).filter((t) => t.built_at && !isBuilding(t.status) && t.status !== 'failed'), [topics.data])
  const q = query.trim().toLowerCase()
  const shown = q
    ? built.filter((t) => [t.name, t.description ?? '', ...t.aliases].some((s) => s.toLowerCase().includes(q)))
    : built
  const count = Object.keys(picked).length
  const toggle = (slug: string) => setPicked((p) => {
    const next = { ...p }
    if (slug in next) delete next[slug]
    else next[slug] = false
    return next
  })

  // In a portal: the composer's form holds the picker, and Enter in its search box must not send the message.
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-bg/60 p-4 backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="map-picker-title"
        className="flex max-h-[calc(100vh-2rem)] w-full max-w-xl flex-col rounded-xl border border-line bg-surface shadow-pop focus:outline-none">
        <header className="flex items-center gap-3 border-b border-line px-4 py-3">
          <GitBranch className="h-4 w-4 text-accent" aria-hidden="true" />
          <h2 id="map-picker-title" className="flex-1 text-[14px] font-semibold text-fg">{title}</h2>
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close"><X /></Button>
        </header>
        <div className="grid gap-2 border-b border-line px-4 py-3">
          <label className="relative block">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-fg-3" aria-hidden="true" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a map…" aria-label="Find a map" autoFocus
              className={cn(inputClass, 'pl-8')} />
          </label>
          <p className="text-[12px] leading-relaxed text-fg-3">
            You see an attached map beside the chat. Turn on <Sparkles className="inline h-3 w-3 text-accent" aria-label="summary" /> <b className="font-medium text-fg-2">Summary for the model</b> to
            also give the model the map as a graph of its milestones, lineage and open problems.
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {topics.isLoading && <div className="flex justify-center py-6"><Spinner label="Loading maps…" /></div>}
          {!topics.isLoading && shown.length === 0 && (
            <p className="px-4 py-6 text-center text-[13px] text-fg-3">{built.length ? 'No map matches.' : 'No maps are built yet. Build one in Evolution.'}</p>
          )}
          <ul aria-label="Maps">
            {shown.map((t) => {
              const already = attached.includes(t.slug)
              const on = t.slug in picked
              return (
                <li key={t.slug} className={cn('border-l-2 px-4 py-2', on ? 'border-accent bg-accent-soft/40' : 'border-transparent')}>
                  <label className={cn('flex items-start gap-3', already ? 'cursor-default opacity-60' : 'cursor-pointer')}>
                    <input type="checkbox" checked={on || already} disabled={already} onChange={() => toggle(t.slug)} className="mt-1 accent-[var(--accent)]" />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2 text-[13.5px] text-fg">
                        <span className="truncate">{t.name}</span>
                        {already && <span className="inline-flex items-center gap-0.5 text-[11px] text-fg-3"><Check className="h-3 w-3" aria-hidden="true" />Attached</span>}
                      </span>
                      {t.description && <span className="line-clamp-1 block text-[12px] text-fg-3">{t.description}</span>}
                      <span className="block font-mono text-[11px] text-fg-3 tabular-nums">{t.paper_count ?? 0} papers · {t.milestone_count ?? 0} milestones</span>
                    </span>
                  </label>
                  {on && (
                    <label className="mt-1.5 ml-7 flex cursor-pointer items-center gap-2 text-[12.5px] text-fg-2">
                      <input type="checkbox" checked={picked[t.slug]} onChange={(e) => setPicked((p) => ({ ...p, [t.slug]: e.target.checked }))} className="accent-[var(--accent)]" />
                      <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                      Summary for the model
                    </label>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
        <footer className="flex items-center gap-2 border-t border-line px-4 py-3">
          <span className="min-w-0 flex-1 text-[12px] text-fg-3">
            {error ? <span className="text-bad">{error}</span> : count ? `${count} selected` : 'Select one or more maps'}
          </span>
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" disabled={!count || busy} onClick={() => onAttach(Object.entries(picked).map(([id, share]) => ({ id, share })))}>
            {busy ? <Spinner className="h-3.5 w-3.5" /> : null}Attach {count > 1 ? `${count} maps` : 'map'}
          </Button>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
