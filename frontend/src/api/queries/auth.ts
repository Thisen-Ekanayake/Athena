import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../client'

export type Role = 'admin' | 'user'

/** An account as the API returns it (`user_out`). */
export interface AuthUser {
  id: string
  email: string
  display_name: string
  role: Role
  is_active: boolean
  must_change_password: boolean
  created_at: string | null
  last_login_at: string | null
}

export interface AuthStatus {
  needs_setup: boolean
  user: AuthUser | null
}

/** A newly created account, or one whose password was reset: the temporary password is shown once. */
export type IssuedUser = AuthUser & { temporary_password: string }

/** Who is logged in, if anyone, and whether the first admin still has to be created. Never answers 401. */
export const useAuthStatus = () =>
  useQuery({
    queryKey: ['auth'],
    queryFn: async () => (await apiClient.get<AuthStatus>('/auth/status')).data,
    staleTime: 5 * 60_000,
    retry: 1,
  })

export const useCurrentUser = () => useAuthStatus().data?.user ?? null

export const useIsAdmin = () => useCurrentUser()?.role === 'admin'

/** Logging in or out changes whose data every other query holds, so the cache starts over. */
function useSignedIn() {
  const queryClient = useQueryClient()
  return (user: AuthUser | null) => {
    queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
    queryClient.setQueryData<AuthStatus>(['auth'], { needs_setup: false, user })
  }
}

export const useLogin = () => {
  const signedIn = useSignedIn()
  return useMutation({
    mutationFn: async (body: { email: string; password: string }) =>
      (await apiClient.post<AuthUser>('/auth/login', body)).data,
    onSuccess: signedIn,
  })
}

export const useSetup = () => {
  const signedIn = useSignedIn()
  return useMutation({
    mutationFn: async (body: { email: string; display_name: string; password: string }) =>
      (await apiClient.post<AuthUser>('/auth/setup', body)).data,
    onSuccess: signedIn,
  })
}

export const useLogout = () => {
  const signedIn = useSignedIn()
  return useMutation({
    mutationFn: async () => {
      await apiClient.post('/auth/logout')
    },
    onSettled: () => signedIn(null),
  })
}

export const useChangePassword = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: { current_password: string; new_password: string }) =>
      (await apiClient.post<AuthUser>('/auth/password', body)).data,
    onSuccess: (user) => queryClient.setQueryData<AuthStatus>(['auth'], { needs_setup: false, user }),
  })
}

// ── Users (admin) ──

export const useUsers = () =>
  useQuery({
    queryKey: ['users'],
    queryFn: async () => (await apiClient.get<AuthUser[]>('/users')).data,
  })

export const useCreateUser = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: { email: string; display_name: string; role: Role }) =>
      (await apiClient.post<IssuedUser>('/users', body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
}

export const useUpdateUser = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: string; role?: Role; is_active?: boolean; display_name?: string }) =>
      (await apiClient.patch<AuthUser>(`/users/${id}`, body)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
}

export const useResetPassword = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => (await apiClient.post<IssuedUser>(`/users/${id}/reset-password`)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
}
