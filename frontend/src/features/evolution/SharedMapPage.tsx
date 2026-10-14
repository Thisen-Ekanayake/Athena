import { useEffect, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { ButtonLink } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { OwlCoin } from '../../ui/OwlCoin'
import { Spinner } from '../../ui/Spinner'
import { countShareView, MapScopeContext, shareScope, useTopicStatus } from './api'
import { TopicView } from './EvolutionPage'

/**
 * A map behind a share link (R2), for people without an account: the same map page, read-only, with a slim header
 * in place of the app's navigation. The token stands in for the map's slug in every request.
 */
export function SharedMapPage() {
  const { token = '' } = useParams<{ token: string }>()
  const scope = useMemo(() => shareScope(token), [token])
  return (
    <MapScopeContext.Provider value={scope}>
      <div className="min-h-screen bg-bg text-fg">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex h-14 max-w-[1500px] items-center gap-3 px-4 md:px-8">
            <OwlCoin size={26} />
            <span className="font-myth text-[17px] text-fg">Athena</span>
            <span className="text-[12.5px] text-fg-3">Shared map · read only</span>
            <ButtonLink to="/login" variant="ghost" size="sm" className="ml-auto">Log in</ButtonLink>
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] px-4 py-6 md:px-8 md:py-8">
          <SharedMap token={token} />
        </main>
      </div>
    </MapScopeContext.Provider>
  )
}

const counted = new Set<string>()  // one view per page load, even when React mounts twice in development

function SharedMap({ token }: { token: string }) {
  const status = useTopicStatus(token)
  useEffect(() => {
    if (counted.has(token)) return
    counted.add(token)
    void countShareView(token)
  }, [token])
  if (status.isLoading) return <Spinner label="Loading the map…" />
  if (status.error || !status.data) {
    return (
      <Notice tone="warn" title="This link no longer opens a map" className="mx-auto max-w-xl">
        It may have expired or been revoked, or sharing was switched off. Ask whoever sent it for a new one.
      </Notice>
    )
  }
  return <TopicView slug={token} />
}
