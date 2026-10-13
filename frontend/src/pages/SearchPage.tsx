import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, GitBranch, Search, Sparkles } from 'lucide-react'
import { useSearch } from '../api/queries/phase4'
import { ItemList } from '../components/items/ItemRow'
import { searchTopics } from '../features/evolution/api'
import { FollowButton } from '../features/inbox/FollowButton'
import { searchPapers } from '../features/search/api'
import { LitReview, ResearchPaper } from '../features/search/ResearchResults'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Notice } from '../ui/Notice'
import { PageHeader } from '../ui/PageHeader'
import { Segmented } from '../ui/Segmented'
import { SkeletonRows } from '../ui/Skeleton'

type Scope = 'library' | 'everywhere'

function SearchForm({ initial, onSearch }: { initial: string; onSearch: (q: string) => void }) {
  const [value, setValue] = useState(initial)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (value.trim().length >= 3) onSearch(value.trim())
  }
  return (
    <form onSubmit={submit} className="mb-4 flex gap-2">
      <label className="flex h-10 min-w-0 flex-1 items-center gap-2.5 rounded-lg border border-line bg-surface px-3 focus-within:border-accent-line focus-within:shadow-[0_0_0_3px_var(--accent-soft)]">
        <Search className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
        <input
          id="search-query"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. retrieval-augmented generation for code"
          aria-label="Search"
          minLength={3}
          maxLength={500}
          className="min-w-0 flex-1 bg-transparent text-[14px] text-fg placeholder:text-fg-3 focus:outline-none"
        />
      </label>
      <Button type="submit" variant="primary" className="h-10 px-4" disabled={value.trim().length < 3}>Search</Button>
    </form>
  )
}

/** If the query names a topic with a research map, point to it. */
function TopicMatch({ q }: { q: string }) {
  const { data } = useQuery({ queryKey: ['evolution', 'search', q], queryFn: () => searchTopics(q), enabled: q.length >= 3, staleTime: 5 * 60 * 1000 })
  if (!data?.found) return null
  return (
    <Link to={`/evolution/${data.topic.slug}`} className="mb-4 flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 hover:border-line-strong">
      <GitBranch className="h-4 w-4 text-accent" aria-hidden="true" />
      <span className="min-w-0 flex-1 text-[13.5px] text-fg-2">
        <span className="font-medium text-fg">{data.topic.name}</span> has a research map: how it developed, its milestones and open problems.
      </span>
      <ArrowRight className="h-4 w-4 text-fg-3" aria-hidden="true" />
    </Link>
  )
}

/** One place for every search: your library, Semantic Scholar, research maps and the AI literature review. */
export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q')?.trim() ?? ''
  const review = params.get('review') === '1'
  const scope: Scope = (params.get('scope') as Scope | null) ?? (review ? 'everywhere' : 'library')

  const update = (next: { q?: string; scope?: Scope; review?: boolean }) => {
    const p = new URLSearchParams()
    p.set('q', next.q ?? q)
    const s = next.scope ?? scope
    if (s !== 'library') p.set('scope', s)
    if (next.review ?? review) p.set('review', '1')
    setParams(p)
  }

  const library = useSearch(q, null, scope === 'library' && q.length >= 3)
  const research = useQuery({
    queryKey: ['research', q, review],
    queryFn: () => searchPapers(q, undefined, review),
    enabled: scope === 'everywhere' && q.length >= 3,
    staleTime: 10 * 60 * 1000,
  })

  return (
    <div className="mx-auto max-w-[920px]">
      <PageHeader
        title={q ? `“${q}”` : 'Search'}
        description="Search your library, or reach out to Semantic Scholar and draft a literature review from what comes back."
        actions={q.length >= 3 && q.length <= 300 && <FollowButton target={{ kind: 'search', query: q }} />}
      />
      <SearchForm key={q} initial={q} onSearch={(next) => update({ q: next })} />

      {q.length < 3 ? (
        <EmptyState icon={Search} title="Search for a paper, a method or a question">Type at least three characters. ⌘K searches from anywhere.</EmptyState>
      ) : (
        <>
          <TopicMatch q={q} />
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Segmented
              label="Where to search"
              value={scope}
              onChange={(s) => update({ scope: s, review: s === 'everywhere' && review })}
              options={[{ value: 'library', label: 'Your library' }, { value: 'everywhere', label: 'Library and Semantic Scholar' }]}
            />
            {!review && (
              <Button variant="ai" size="sm" className="ml-auto" onClick={() => update({ scope: 'everywhere', review: true })}>
                <Sparkles /> Write a literature review
              </Button>
            )}
          </div>

          {scope === 'library' ? (
            library.isLoading ? (
              <SkeletonRows count={5} />
            ) : library.error ? (
              <Notice tone="error" title="Search failed">Check that the API is running, then try again.</Notice>
            ) : library.data?.items.length ? (
              <ItemList items={library.data.items} />
            ) : (
              <EmptyState icon={Search} title="Nothing in your library matches">
                Try other words, or search Semantic Scholar as well.
                <div className="mt-3"><Button size="sm" onClick={() => update({ scope: 'everywhere' })}>Search Semantic Scholar too</Button></div>
              </EmptyState>
            )
          ) : (
            <div className="grid gap-4">
              {review && <LitReview query={q} review={research.data?.lit_review ?? null} pending={research.isFetching} />}
              {research.isLoading ? (
                <SkeletonRows count={5} />
              ) : research.error ? (
                <Notice tone="error" title="Search failed">{research.error.message}. Semantic Scholar may be rate-limiting; try again in a minute.</Notice>
              ) : research.data ? (
                <>
                  <p className="text-[12.5px] text-fg-3">
                    {research.data.papers.length} papers · {research.data.local_count} from your library · {research.data.live_count} from Semantic Scholar
                  </p>
                  {research.data.papers.length ? (
                    <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
                      {research.data.papers.map((p, i) => <ResearchPaper key={p.id || `${p.source}-${i}`} paper={p} />)}
                    </div>
                  ) : (
                    <EmptyState icon={Search} title={`No papers found for “${q}”`}>Try a broader query.</EmptyState>
                  )}
                </>
              ) : null}
            </div>
          )}
        </>
      )}
    </div>
  )
}
