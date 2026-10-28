import { useState } from 'react'
import { Eye, ExternalLink, Maximize2, Minimize2, Sparkles, X } from 'lucide-react'
import { useMapDigest, type MapDigest } from '../../api/queries/chats'
import { ButtonLink, Button } from '../../ui/Button'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { EvolutionGraph } from '../evolution/EvolutionGraph'
import { MapPaperPanel } from '../evolution/MapPaperPanel'
import { useTopicGraph } from '../evolution/api/graph'
import { isBuilding, useTopicStatus } from '../evolution/api/topics'
import { useFullScreen } from '../evolution/useFullScreen'

type Level = MapDigest['level']
const LEVEL_LABEL: Record<Level, string> = { full: 'Full', compact: 'Compact', minimal: 'Minimal' }

/**
 * A research map beside a chat or project (give it ``key={slug}``): its lineage graph, the paper picked in it, full
 * screen, and a link to the whole map with its timeline, open problems and the rest. ``share`` is the switch that
 * gives the model the map as a graph; with ``chatId`` the panel can show exactly what the model gets.
 */
export function MapPanel({ slug, paperId, onSelect, onClose, share, chatId, className }: {
  slug: string
  paperId: string | null
  onSelect: (paperId: string | null) => void
  onClose: () => void
  /** ``note`` says what the switch reaches, when more than this chat (a project's map) */
  share?: { on: boolean; onChange: (on: boolean) => void; pending?: boolean; note?: string }
  chatId?: string
  className?: string
}) {
  const status = useTopicStatus(slug)
  const current = status.data
  const readable = !!current && !isBuilding(current.status) && current.status !== 'failed'
  const graph = useTopicGraph(slug, 250, current ? `${current.status}:${current.built_at ?? ''}` : '', readable)
  const { ref, on: fullScreen, toggle } = useFullScreen<HTMLDivElement>()
  const [seeing, setSeeing] = useState(false)

  const fullMap = `/evolution/${slug}${paperId ? `?paper=${paperId}` : ''}`
  return (
    <aside className={cn('flex min-h-0 flex-col border-l border-line bg-surface', className)} aria-label="Research map">
      <header className="flex items-center gap-1 border-b border-line px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13.5px] font-medium text-fg">{current?.name ?? slug}</p>
          <p className="text-[11.5px] text-fg-3">
            {graph.data ? `${graph.data.total_papers} papers · ${graph.data.nodes.filter((n) => n.is_milestone).length} milestones` : 'Research map'}
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label="Full screen" title="Show the map on the whole screen" disabled={!graph.data}><Maximize2 /></Button>
        <ButtonLink to={fullMap} variant="ghost" size="sm" title="The whole map: timeline, reading path, open problems, people…"><ExternalLink /> Full map</ButtonLink>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close" title="Close"><X /></Button>
      </header>
      {share && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2 text-[12.5px]">
          <label className="flex cursor-pointer items-center gap-2 text-fg-2">
            <input type="checkbox" checked={share.on} disabled={share.pending} onChange={(e) => share.onChange(e.target.checked)} className="accent-[var(--accent)]" />
            <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
            Summary for the model
          </label>
          <span className="text-[11.5px] text-fg-3">{share.note ?? (share.on ? 'The model gets this map as a graph.' : 'Only you see this map.')}</span>
          {share.on && chatId && (
            <Button variant="ghost" size="sm" className="ml-auto" aria-expanded={seeing} onClick={() => setSeeing((s) => !s)}>
              <Eye /> {seeing ? 'Hide' : 'What the model sees'}
            </Button>
          )}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {seeing && share?.on && chatId && <ModelView chatId={chatId} slug={slug} />}
        {status.isLoading || graph.isLoading ? (
          <div className="grid place-items-center py-16"><Spinner label="Loading the map…" /></div>
        ) : !readable ? (
          <p className="p-4 text-[13px] text-fg-3">This map is {current?.status === 'failed' ? 'not built (its build failed)' : 'still being built'}.</p>
        ) : !graph.data ? (
          <p className="p-4 text-[13px] text-bad">The map could not be loaded.</p>
        ) : (
          <div className="grid gap-3 p-3">
            <div ref={ref} className={cn('relative min-w-0', fullScreen && 'fixed inset-0 z-[60] bg-[var(--map-bg)]')}>
              <EvolutionGraph
                nodes={graph.data.nodes}
                edges={graph.data.edges}
                looseEdges={[]}
                selectedId={paperId}
                onSelect={onSelect}
                showCitations={false}
                className={fullScreen ? 'h-full rounded-none border-0' : 'h-[420px]'}
                actions={fullScreen && (
                  <Button variant="secondary" size="sm" onClick={toggle} title="Leave full screen (Esc)"><Minimize2 /> Exit full screen</Button>
                )}
              />
            </div>
            {paperId ? (
              <MapPaperPanel slug={slug} paperId={paperId} onSelect={onSelect} onClose={() => onSelect(null)} />
            ) : (
              <p className="text-[12.5px] text-fg-3">Select a paper to see what it built on and what built on it.</p>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}

/** The graph exactly as the model gets it, at the level the next turn would use (or another, to compare). */
function ModelView({ chatId, slug }: { chatId: string; slug: string }) {
  const digest = useMapDigest(chatId, slug, true)
  const [level, setLevel] = useState<Level | null>(null)
  if (digest.isLoading) return <div className="flex justify-center border-b border-line py-4"><Spinner /></div>
  if (!digest.data) return <p className="border-b border-line px-3 py-2 text-[12px] text-bad">The model’s view could not be loaded.</p>
  const d = digest.data
  const shown = level ?? d.level
  return (
    <section className="grid gap-2 border-b border-line bg-surface-2/50 px-3 py-3" aria-label="What the model sees">
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-3">
        <Segmented label="Detail" value={shown} onChange={setLevel}
          options={(['full', 'compact', 'minimal'] as Level[]).map((l) => ({ value: l, label: `${LEVEL_LABEL[l]}${l === d.level ? ' ·  next' : ''}`, title: `About ${d.levels[l].tokens.toLocaleString()} tokens` }))} />
        <span>
          About {d.levels[shown].tokens.toLocaleString()} tokens. The next turn uses <b className="font-medium text-fg-2">{LEVEL_LABEL[d.level].toLowerCase()}</b>: the most
          detail that fits this map’s share of the context (~{d.budget.toLocaleString()} tokens).
        </span>
      </div>
      <pre className="max-h-72 overflow-auto rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-fg-2">{d.levels[shown].text}</pre>
    </section>
  )
}
