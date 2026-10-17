import type { ReactElement } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AxiosError, AxiosHeaders, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios'
import { apiClient } from '../api/client'
import { queryClient } from '../api/queryClient'

/** A request the app made, as the fake API saw it. */
export interface Call {
  method: string
  url: string
  params: Record<string, unknown>
  body: unknown
}

export interface Reply {
  status?: number
  data?: unknown
}

/** Answers keyed by `"METHOD /path"` (the path under /api/v1), as a reply or a function of the request. */
export type ApiRoutes = Record<string, Reply | ((call: Call) => Reply)>

const realAdapter = apiClient.defaults.adapter

/**
 * Fake the API under the app's own axios client: its interceptors and the query hooks run as they do in the app.
 * A request no route answers gets a 404. Returns every request made, in order.
 */
export function mockApi(routes: ApiRoutes): Call[] {
  const calls: Call[] = []
  const adapter: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
    const call: Call = {
      method: (config.method ?? 'get').toUpperCase(),
      url: config.url ?? '',
      params: config.params ?? {},
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    }
    calls.push(call)
    const route = routes[`${call.method} ${call.url}`]
    const reply = typeof route === 'function' ? route(call) : route ?? { status: 404, data: { detail: 'Not mocked' } }
    const status = reply.status ?? 200
    const response = { data: reply.data ?? null, status, statusText: String(status), headers: new AxiosHeaders(), config }
    if (status >= 400) {
      throw new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_RESPONSE, config, null, response)
    }
    return response
  }
  apiClient.defaults.adapter = adapter
  return calls
}

/** Put the real adapter back (setup.ts does this after every test). */
export function restoreApi() {
  apiClient.defaults.adapter = realAdapter
}

/**
 * Render with the app's query cache and a router at ``route``. ``path`` is the route pattern the element sits
 * under, for pages that read URL params; any other path renders its own pathname, so a redirect shows where it went.
 */
export function renderWithProviders(ui: ReactElement, { route = '/', path = '*' }: { route?: string; path?: string } = {}) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
          {path !== '*' && <Route path="*" element={<Location />} />}
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Where a redirect landed: the path, with the router state as JSON in ``data-state``. */
function Location() {
  const { pathname, state } = useLocation()
  return <p data-testid="location" data-state={JSON.stringify(state ?? null)}>{pathname}</p>
}
