import { useDeferredValue, useState, type ReactNode } from 'react'
import { Check, Plus, Search } from 'lucide-react'
import { useLists } from '../../api/queries/saved'
import { useReviews } from '../../api/queries/reviews'
import { useSearch } from '../../api/queries/search'
import { useAddToProject, type ItemToAdd, type Project } from '../../api/queries/projects'
import { Button } from '../../ui/Button'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { useIdeaChecks } from '../evolution/api/ask'
import { useEvolutionTopics } from '../evolution/api/topics'

type Tab = 'papers' | 'maps' | 'reviews' | 'ideas' | 'lists'

interface Row {
  key: string
  ref: string
  title: string
  subtitle?: string | null
  item: ItemToAdd
}

/** Pick things of Athena's to add to a project: papers from the library, maps, reviews, idea checks, saved lists. */
export function AddKnowledge({ project }: { project: Project }) {
  const [tab, setTab] = useState<Tab>('papers')
  const [q, setQ] = useState('')
  const query = useDeferredValue(q.trim())
  const search = useSearch(query, null, tab === 'papers')
  const maps = useEvolutionTopics()
  const reviews = useReviews()
  const ideas = useIdeaChecks()
  const lists = useLists()
  const add = useAddToProject()
  const have = new Set(project.items.map((i) => i.ref))
  const mapRefs = new Map(project.items.filter((i) => i.slug).map((i) => [i.slug, i.ref]))

  const match = (s: string) => !query || s.toLowerCase().includes(query.toLowerCase())
  let rows: Row[]
  let loading: boolean
  if (tab === 'papers') {
    loading = search.isFetching
    rows = (search.data?.items ?? []).map((p) => ({
      key: p.id, ref: `item:${p.id}`, title: p.title,
      subtitle: [p.authors?.slice(0, 3).join(', '), p.published_at?.slice(0, 4)].filter(Boolean).join(' · '),
      item: { kind: 'paper', id: p.id },
    }))
  } else if (tab === 'maps') {
    loading = maps.isLoading
    rows = (maps.data ?? []).filter((t) => t.built_at && match(t.name)).map((t) => ({
      key: t.slug, ref: mapRefs.get(t.slug) ?? `map-slug:${t.slug}`, title: t.name, subtitle: 'Research map', item: { kind: 'map', id: t.slug },
    }))
  } else if (tab === 'reviews') {
    loading = reviews.isLoading
    rows = (reviews.data ?? []).filter((r) => r.status === 'done' && match(r.title)).map((r) => ({
      key: r.id, ref: `review:${r.id}`, title: r.title, subtitle: `${r.cited} papers cited`, item: { kind: 'review', id: r.id },
    }))
  } else if (tab === 'ideas') {
    loading = ideas.isLoading
    rows = (ideas.data ?? []).filter((c) => match(c.idea)).map((c) => ({
      key: c.id, ref: `idea:${c.id}`, title: c.idea, subtitle: `${c.papers} similar papers · ${c.open_themes} open problems`, item: { kind: 'idea_check', id: c.id },
    }))
  } else {
    loading = lists.isLoading
    rows = (lists.data ?? []).filter((l) => match(l.name)).map((l) => ({
      key: l.id, ref: `list:${l.id}`, title: l.name, subtitle: `${l.item_count} saved items`, item: { kind: 'list', id: l.id },
    }))
  }

  let empty: ReactNode = 'Nothing to add here yet.'
  if (tab === 'papers') empty = query.length > 2 ? 'No papers match.' : 'Search the library by title, author or topic.'

  return (
    <div className="grid gap-2 p-3">
      <Segmented<Tab>
        label="What to add"
        value={tab}
        onChange={setTab}
        className="justify-self-start"
        options={[
          { value: 'papers', label: 'Papers' }, { value: 'maps', label: 'Maps' }, { value: 'reviews', label: 'Reviews' },
          { value: 'ideas', label: 'Idea checks' }, { value: 'lists', label: 'Lists' },
        ]}
      />
      <label className="relative block">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-fg-3" aria-hidden="true" />
        <input value={q} onChange={(e) => setQ(e.target.value)} autoFocus placeholder={tab === 'papers' ? 'Search the library' : 'Filter'} aria-label="Search" className={cn(inputClass, 'w-full pl-8')} />
      </label>
      <ul className="max-h-72 overflow-y-auto">
        {loading && <li className="flex justify-center py-4"><Spinner /></li>}
        {!loading && rows.length === 0 && <li className="px-1 py-3 text-[12.5px] text-fg-3">{empty}</li>}
        {rows.map((r) => {
          const inProject = have.has(r.ref)
          return (
            <li key={r.key} className="flex items-center gap-2 rounded-lg px-1.5 py-1.5 hover:bg-surface-2">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] text-fg">{r.title}</span>
                {r.subtitle && <span className="block truncate text-[11.5px] text-fg-3">{r.subtitle}</span>}
              </span>
              {inProject ? (
                <span className="inline-flex items-center gap-1 text-[11.5px] text-good"><Check className="h-3 w-3" aria-hidden="true" />Added</span>
              ) : (
                <Button variant="ghost" size="sm" disabled={add.isPending && add.variables?.item === r.item}
                  onClick={() => add.mutate({ projectId: project.id, item: r.item })}>
                  <Plus /> Add
                </Button>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
