import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight, Bookmark, CornerDownLeft, FileText, GitBranch, House, Layers, Newspaper, Search, Settings, Sparkles, TrendingUp,
  type LucideIcon,
} from 'lucide-react'
import { useClusters, useSearch } from '../../api/queries/phase4'
import { useEvolutionTopics } from '../../features/evolution/api'
import { usePaletteStore, usePanelStore } from '../../store/panelStore'
import { Kbd } from '../../ui/Kbd'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'

interface Entry {
  id: string
  group: string
  icon: LucideIcon
  label: ReactNode
  hint?: string
  ai?: boolean
  run: () => void
}

const PAGES: { label: string; to: string; icon: LucideIcon; keywords: string }[] = [
  { label: 'Home', to: '/', icon: House, keywords: 'dashboard overview start' },
  { label: 'Feed', to: '/feed', icon: Newspaper, keywords: 'latest papers posts ranked' },
  { label: 'Trending', to: '/trending', icon: TrendingUp, keywords: 'rising hot popular' },
  { label: 'Clusters', to: '/clusters', icon: Layers, keywords: 'themes groups topics' },
  { label: 'Evolution', to: '/evolution', icon: GitBranch, keywords: 'lineage history graph gaps milestones' },
  { label: 'Saved', to: '/saved', icon: Bookmark, keywords: 'lists reading bookmarks' },
  { label: 'Settings', to: '/settings', icon: Settings, keywords: 'sources keys appearance sync health' },
]

function useDebounced<T>(value: T, ms: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

const matches = (text: string, words: string[]) => {
  const hay = text.toLowerCase()
  return words.every((w) => hay.includes(w))
}

/** One search for the whole app: pages, topics, clusters and papers, plus the AI actions. Opened with ⌘K. */
export function CommandPalette() {
  const isOpen = usePaletteStore((s) => s.isOpen)
  if (!isOpen) return null
  return <PaletteDialog />
}

function PaletteDialog() {
  const query = usePaletteStore((s) => s.query)
  const setQuery = usePaletteStore((s) => s.setQuery)
  const close = usePaletteStore((s) => s.close)
  const openItem = usePanelStore((s) => s.open)
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(0)

  const q = query.trim()
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  const debounced = useDebounced(q, 250)
  const papers = useSearch(debounced, null, debounced.length > 2)
  const { data: topics } = useEvolutionTopics()
  const { data: clusters } = useClusters()

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  const go = (to: string) => () => {
    close()
    navigate(to)
  }

  const entries: Entry[] = []
  {
    const out = entries
    const pages = words.length ? PAGES.filter((p) => matches(`${p.label} ${p.keywords}`, words)) : PAGES
    if (q) {
      for (const t of (topics ?? []).filter((t) => matches(`${t.name} ${t.aliases.join(' ')}`, words)).slice(0, 4)) {
        out.push({ id: `topic:${t.slug}`, group: 'Topics', icon: GitBranch, label: t.name, hint: 'Evolution', run: go(`/evolution/${t.slug}`) })
      }
      for (const c of (clusters ?? []).filter((c) => c.label && matches(c.label, words)).slice(0, 3)) {
        out.push({ id: `cluster:${c.id}`, group: 'Topics', icon: Layers, label: c.label, hint: `Cluster · ${c.item_count}`, run: go(`/clusters/${c.id}`) })
      }
      for (const item of (papers.data?.items ?? []).slice(0, 6)) {
        out.push({
          id: `item:${item.id}`, group: 'Papers and posts', icon: FileText, label: item.title, hint: item.source.name,
          run: () => {
            close()
            openItem(item)
          },
        })
      }
      out.push(
        { id: 'all', group: 'Search', icon: Search, label: <>See all results for “{q}”</>, run: go(`/search?q=${encodeURIComponent(q)}`) },
        { id: 'review', group: 'Ask Athena', icon: Sparkles, ai: true, label: <>Write a literature review on “{q}”</>, run: go(`/search?q=${encodeURIComponent(q)}&review=1`) },
        { id: 'evolution', group: 'Ask Athena', icon: GitBranch, label: <>Trace how “{q}” evolved</>, run: go(`/evolution?q=${encodeURIComponent(q)}`) },
      )
    }
    for (const p of pages) out.push({ id: `page:${p.to}`, group: 'Go to', icon: p.icon, label: p.label, run: go(p.to) })
  }

  const current = Math.min(active, entries.length - 1)

  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [current])

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      close()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((current + 1) % entries.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((current - 1 + entries.length) % entries.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      entries[current]?.run()
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-bg/60 px-4 pt-[12vh] backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div role="dialog" aria-modal="true" aria-label="Search and ask" onKeyDown={onKeyDown} className="w-full max-w-[600px] overflow-hidden rounded-xl border border-line bg-surface shadow-pop">
        <div className="flex items-center gap-3 border-b border-line px-4">
          {papers.isFetching ? <Spinner /> : <Search className="h-4 w-4 text-fg-3" aria-hidden="true" />}
          <input
            ref={inputRef}
            id="command-palette-input"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            placeholder="Search papers and topics, or ask a question"
            aria-label="Search or ask"
            aria-controls="command-palette-list"
            autoComplete="off"
            className="h-12 min-w-0 flex-1 bg-transparent text-[15px] text-fg placeholder:text-fg-3 focus:outline-none"
          />
          <Kbd>esc</Kbd>
        </div>
        <div ref={listRef} id="command-palette-list" role="listbox" className="max-h-[380px] overflow-y-auto p-1.5">
          {entries.map((entry, i) => {
            const header = i === 0 || entries[i - 1].group !== entry.group ? entry.group : null
            const Icon = entry.icon
            return (
              <div key={entry.id}>
                {header && <p className="px-2.5 pt-2.5 pb-1 text-[11px] text-fg-3">{header}</p>}
                <button
                  type="button"
                  role="option"
                  aria-selected={i === current}
                  data-active={i === current}
                  onMouseMove={() => i !== current && setActive(i)}
                  onClick={entry.run}
                  className={cn(
                    'relative flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13.5px] text-fg',
                    i === current && (entry.ai ? 'bg-accent-soft' : 'bg-surface-2'),
                  )}
                >
                  {entry.ai && <span className="ai-ring" data-active={i === current} style={{ opacity: i === current ? 1 : 0 }} aria-hidden="true" />}
                  <Icon className={cn('h-4 w-4 shrink-0', entry.ai ? 'text-accent' : 'text-fg-3')} aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{entry.label}</span>
                  {entry.hint && <span className="max-w-[40%] truncate text-[12px] text-fg-3">{entry.hint}</span>}
                  {i === current && <ArrowRight className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" />}
                </button>
              </div>
            )
          })}
          {q.length > 0 && q.length < 3 && <p className="px-2.5 py-2 text-[12.5px] text-fg-3">Type at least 3 characters to search papers.</p>}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-[11.5px] text-fg-3">
          <span className="inline-flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> move</span>
          <span className="inline-flex items-center gap-1"><Kbd><CornerDownLeft className="h-3 w-3" /></Kbd> open</span>
        </div>
      </div>
    </div>
  )
}
