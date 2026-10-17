import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach } from 'vitest'
import { queryClient } from '../api/queryClient'
import { restoreApi } from './utils'

// A failed request in a test is the answer under test: don't retry it.
queryClient.setDefaultOptions({ queries: { retry: false } })

beforeEach(() => {
  try {
    localStorage.clear()
  } catch {
    // jsdom without storage: nothing to clear
  }
})

afterEach(() => {
  cleanup()
  queryClient.clear()
  restoreApi()
})

// jsdom has no IntersectionObserver; the feed uses one to load the next page.
class NoIntersections {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return [] }
}
globalThis.IntersectionObserver ??= NoIntersections as unknown as typeof IntersectionObserver
