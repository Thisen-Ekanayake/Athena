import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './client'
import { apiErrorMessage } from './error'
import { queryClient } from './queryClient'
import { mockApi } from '../test/utils'

describe('apiErrorMessage', () => {
  it("prefers the API's detail, then the error's message, then the fallback", () => {
    expect(apiErrorMessage({ response: { data: { detail: 'Weights must add up to 1' } }, message: 'Request failed' }, 'x'))
      .toBe('Weights must add up to 1')
    expect(apiErrorMessage({ message: 'Network Error' }, 'x')).toBe('Network Error')
    expect(apiErrorMessage(null, 'Try again')).toBe('Try again')
  })
})

describe('the session interceptor', () => {
  afterEach(() => vi.restoreAllMocks())

  const failing = (url: string, status: number, detail?: string) => {
    mockApi({ [`GET ${url}`]: { status, data: detail ? { detail } : {} } })
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    return { invalidate, request: apiClient.get(url) }
  }

  it('re-reads who is logged in when a session ends', async () => {
    const { invalidate, request } = failing('/feed', 401)
    await expect(request).rejects.toMatchObject({ response: { status: 401 } })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['auth'] })
  })

  it('does the same when a temporary password must be changed', async () => {
    const { invalidate, request } = failing('/feed', 403, 'password_change_required')
    await expect(request).rejects.toMatchObject({ response: { status: 403 } })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['auth'] })
  })

  it('leaves other refusals alone', async () => {
    const { invalidate, request } = failing('/admin/users', 403, 'Admins only')
    await expect(request).rejects.toMatchObject({ response: { status: 403 } })
    expect(invalidate).not.toHaveBeenCalled()
  })

  it("doesn't loop on the auth routes themselves", async () => {
    const { invalidate, request } = failing('/auth/login', 401, 'Wrong email or password')
    await expect(request).rejects.toMatchObject({ response: { data: { detail: 'Wrong email or password' } } })
    expect(invalidate).not.toHaveBeenCalled()
  })

  it('passes answers through untouched', async () => {
    mockApi({ 'GET /feed': { data: { items: [] } } })
    await expect(apiClient.get('/feed')).resolves.toMatchObject({ status: 200, data: { items: [] } })
  })
})
