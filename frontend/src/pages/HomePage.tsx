import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { ArrowRight, Compass, GitBranch, Newspaper, Sparkles, TrendingUp } from 'lucide-react'
import { useFeed } from '../api/queries/feed'
import { useRising } from '../api/queries/momentum'
import { RisingList } from '../features/momentum/RisingList'
import { topicGapsQuery, useEvolutionTopics } from '../features/evolution/api'
import { AstrolabePortal } from '../features/astrolabe/AstrolabePortal'
import { ItemList } from '../components/items/ItemRow'
import { usePaletteStore } from '../store/panelStore'
import { Button, ButtonLink } from '../ui/Button'
import { Card, CardHeader } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Skeleton } from '../ui/Skeleton'

function greeting() {
  const now = new Date()
  const h = now.getHours()
  return {
    hello: h < 5 ? 'Good evening' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening',
    date: now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' }),
  }
}

function TileLink({ to, children }: { to: string; children: string }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1 text-[12px] text-fg-3 hover:text-fg">
      {children} <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
    </Link>
  )
}

function TileSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid gap-4 px-4 pt-1 pb-4" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="grid gap-2">
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      ))}
    </div>
  )
}

function TileEmpty({ children }: { children: ReactNode }) {
  return <p className="px-4 pt-1 pb-4 text-[13px] text-fg-3">{children}</p>
}

/** The start page: what is new, what is rising, and where your research maps stand. */
export function HomePage() {
  const openPalette = usePaletteStore((s) => s.open)
  const { hello, date } = greeting()
  const today = useFeed('date', null, '24h', null, 1)
  const top = useFeed('score', null, '7d', null, 5)
  const rising = useRising('7d', 5)
  const topics = useEvolutionTopics()
  const ready = (topics.data ?? []).filter((t) => t.status === 'ready')
  const gaps = useQueries({ queries: ready.map((t) => topicGapsQuery(t.slug)) })

  const newToday = today.data?.pages[0]?.pagination.total
  const topItems = top.data?.pages[0]?.items ?? []
  const newGaps = gaps
    .flatMap((g) => (g.data ? g.data.themes.filter((t) => t.status === 'new').map((t) => ({ theme: t, topic: g.data.topic })) : []))
    .sort((a, b) => b.theme.size - a.theme.size)
    .slice(0, 4)
  const gapsLoading = topics.isLoading || gaps.some((g) => g.isLoading)

  return (
    <div className="mx-auto grid max-w-[1200px] gap-6">
      <section className="grid items-center gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <div className="grid gap-3 py-4 max-lg:order-2">
          <p className="text-[12.5px] text-fg-3">{date}</p>
          <h1 className="font-myth text-[clamp(38px,5vw,54px)] leading-[1.02] font-normal">{hello}</h1>
          <p className="max-w-[44ch] text-[15px] text-fg-2">
            {newToday === undefined
              ? 'Here is what moved in your research since you were last here.'
              : newToday === 0
                ? 'Nothing new in the last day yet. Sync your sources to fetch the latest.'
                : `${newToday} new ${newToday === 1 ? 'item' : 'items'} in the last day.`}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <ButtonLink to="/feed" variant="primary">Open feed <ArrowRight /></ButtonLink>
            <Button variant="ai" onClick={() => openPalette()}><Sparkles /> Ask Athena</Button>
          </div>
        </div>
        <AstrolabePortal onCoreClick={() => openPalette()} className="h-[clamp(300px,36vw,460px)]" />
      </section>

      <div className="grid items-start gap-3 lg:grid-cols-6">
        <Card className="lg:col-span-4">
          <CardHeader icon={Newspaper} title="Top this week" action={<TileLink to="/feed">Open feed</TileLink>} />
          {top.isLoading ? <TileSkeleton rows={4} /> : topItems.length ? <ItemList items={topItems} showSummary={false} bare /> : <TileEmpty>Nothing scored this week yet.</TileEmpty>}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader icon={TrendingUp} title="Rising fast" action={<TileLink to="/rising">All</TileLink>} />
          {rising.isLoading ? (
            <TileSkeleton />
          ) : rising.data?.length ? (
            <RisingList items={rising.data} period="7d" bare />
          ) : (
            <TileEmpty>No paper gained citations this week. Counts are checked once a day.</TileEmpty>
          )}
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader icon={GitBranch} title="Research maps" action={<TileLink to="/evolution">Evolution</TileLink>} />
          {topics.isLoading ? (
            <TileSkeleton />
          ) : topics.data?.length ? (
            <ul className="divide-y divide-line">
              {topics.data.map((t) => (
                <li key={t.slug}>
                  <Link to={`/evolution/${t.slug}`} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-2/60">
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-medium text-fg">{t.name}</span>
                      <span className="block text-[12px] text-fg-3">
                        {t.status === 'ready' || t.status === 'refining' ? `${t.paper_count ?? 0} papers · ${t.milestone_count ?? 0} milestones` : t.status_detail ?? 'Not built yet'}
                      </span>
                    </span>
                    {t.status !== 'ready' && <Chip tone={t.status === 'failed' ? 'bad' : 'neutral'}>{t.status}</Chip>}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <TileEmpty>No research maps yet. Build a topic to trace how a field developed.</TileEmpty>
          )}
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader icon={Compass} title="New open problems" action={ready.length ? <TileLink to={`/evolution/${ready[0].slug}?tab=gaps`}>Gaps</TileLink> : null} />
          {gapsLoading ? (
            <TileSkeleton />
          ) : newGaps.length ? (
            <ul className="divide-y divide-line">
              {newGaps.map(({ theme, topic }) => (
                <li key={`${topic.slug}:${theme.id}`}>
                  <Link to={`/evolution/${topic.slug}?tab=gaps`} className="grid gap-0.5 px-4 py-3 hover:bg-surface-2/60">
                    <span className="flex flex-wrap items-center gap-2 text-[13.5px] font-medium text-fg">
                      {theme.label} <Chip tone="accent">New</Chip>
                    </span>
                    <span className="text-[12px] text-fg-3">{topic.name} · {theme.size} {theme.size === 1 ? 'mention' : 'mentions'}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <TileEmpty>No new open problems in your research maps this year.</TileEmpty>
          )}
        </Card>
      </div>
    </div>
  )
}
