import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, GitBranch, Search, Sparkles } from 'lucide-react'
import { useSearch } from '../api/queries/search'
import { ItemList } from '../components/items/ItemRow'
import { searchTopics } from '../features/evolution/api'
import { FollowButton } from '../features/inbox/FollowButton'
import { searchPapers } from '../features/search/api'
import { ResearchPaper } from '../features/search/ResearchResults'
import { ReviewView } from '../features/reviews/ReviewView'
import { apiErrorMessage } from '../api/error'
import { useStartReview } from '../api/queries/reviews'
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

/** Starts a literature review of the query, saying first whether a research map will ground it. */
function ReviewStarter({ q, onStarted }: { q: string; onStarted: (id: string) => void }) {
  const { data: match, isLoading } = useQuery({ queryKey: ['evolution', 'search', q], queryFn: () => searchTopics(q), enabled: q.length >= 3, staleTime: 5 * 60 * 1000 })
  const start = useStartReview()
  return (
    <section className="relative grid gap-3 rounded-xl border border-line bg-surface p-4">
      <span className="ai-ring" aria-hidden="true" />
      <div className="grid gap-1">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold text-fg"><Sparkles className="h-4 w-4 text-accent" aria-hidden="true" /> Write a literature review on “{q}”</h2>
        <p className="text-[13px] text-fg-2">
          {isLoading ? 'Looking for a research map that covers it…'
            : match?.found ? <>It will be grounded in the map <b className="text-fg">{match.topic.name}</b>: how the field developed, its main approaches and open problems, citing the papers’ own text. It takes a few minutes and is saved in your Library.</>
              : <>No research map covers this, so it will be written from search results’ abstracts, with checked citations. Build a map of the topic for a fuller review.</>}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ai" disabled={start.isPending || isLoading} onClick={() => start.mutate({ query: q }, { onSuccess: (r) => onStarted(r.id) })}>
          <Sparkles /> {start.isPending ? 'Starting…' : 'Write the review'}
        </Button>
        {start.error && (
          <span className="text-[12.5px] text-bad">
            {apiErrorMessage(start.error, 'Could not start the review')}{' '}
            <Link to="/library/reviews" className="underline">Your reviews</Link>
          </span>
        )}
      </div>
    </section>
  )
}

/** One place for every search: your library, Semantic Scholar, research maps and literature reviews. */
export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q')?.trim() ?? ''
  const review = params.get('review') === '1'
  const reviewId = params.get('rid')
  const scope: Scope = (params.get('scope') as Scope | null) ?? 'library'

  const update = (next: { q?: string; scope?: Scope; review?: boolean; rid?: string | null }) => {
    const p = new URLSearchParams()
    p.set('q', next.q ?? q)
    const s = next.scope ?? scope
    if (s !== 'library') p.set('scope', s)
    const sameQuery = (next.q ?? q) === q
    if (next.review ?? (review && sameQuery)) p.set('review', '1')
    const rid = next.rid === undefined ? (sameQuery ? reviewId : null) : next.rid
    if (rid) p.set('rid', rid)
    setParams(p)
  }

  const library = useSearch(q, null, scope === 'library' && q.length >= 3)
  const research = useQuery({
    queryKey: ['research', q],
    queryFn: () => searchPapers(q),
    enabled: scope === 'everywhere' && q.length >= 3,
    staleTime: 10 * 60 * 1000,
  })

  return (
    <div className="mx-auto max-w-[920px]">
      <PageHeader
        title={q ? `“${q}”` : 'Search'}
        description="Search your library by name or by meaning, reach out to Semantic Scholar, or have a literature review written."
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
              onChange={(s) => update({ scope: s })}
              options={[{ value: 'library', label: 'Your library' }, { value: 'everywhere', label: 'Library and Semantic Scholar' }]}
            />
            {!review && !reviewId && (
              <Button variant="ai" size="sm" className="ml-auto" onClick={() => update({ review: true })}>
                <Sparkles /> Write a literature review
              </Button>
            )}
          </div>

          {reviewId ? (
            <div className="mb-4"><ReviewView id={reviewId} compact /></div>
          ) : review ? (
            <div className="mb-4"><ReviewStarter q={q} onStarted={(rid) => update({ rid, review: false })} /></div>
          ) : null}

          {scope === 'library' ? (
            library.isLoading ? (
              <SkeletonRows count={5} />
            ) : library.error ? (
              <Notice tone="error" title="Search failed">Check that the API is running, then try again.</Notice>
            ) : library.data?.items.length ? (
              <ItemList items={library.data.items} collapseHidden={false} />
            ) : (
              <EmptyState icon={Search} title="Nothing in your library matches">
                Try other words, or search Semantic Scholar as well.
                <div className="mt-3"><Button size="sm" onClick={() => update({ scope: 'everywhere' })}>Search Semantic Scholar too</Button></div>
              </EmptyState>
            )
          ) : (
            <div className="grid gap-4">
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
