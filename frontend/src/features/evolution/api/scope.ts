/** Where a map's read routes live: the account's routes, or a share link's read-only ones. */
import { createContext, useContext } from 'react'

/**
 * Where a map's read routes live. Logged in, they are /evolution/topics/<slug>; behind a share link (R2), the same
 * answers come from /share/<token> and the map is read-only: nothing that needs an account (read ticks, pins,
 * questions, follows, links to other pages). Query keys start with ``key`` so the two caches stay apart.
 */
export interface MapScope {
  base: (slug: string) => string
  key: string
  readOnly: boolean
}

export const ACCOUNT_SCOPE: MapScope = { base: (slug) => `/evolution/topics/${slug}`, key: 'evolution', readOnly: false }

export const shareScope = (token: string): MapScope => ({ base: () => `/share/${token}`, key: `share:${token}`, readOnly: true })

export const MapScopeContext = createContext<MapScope>(ACCOUNT_SCOPE)

export const useMapScope = () => useContext(MapScopeContext)
