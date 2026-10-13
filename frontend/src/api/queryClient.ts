import { QueryClient } from '@tanstack/react-query'

/** The app's one query cache, shared with the axios client so a 401 can refresh who is logged in. */
export const queryClient = new QueryClient()
