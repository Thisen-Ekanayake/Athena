/** Extract a human-readable message from an axios/API error without using `any`. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const e = error as { response?: { data?: { detail?: string } }; message?: string }
  return e?.response?.data?.detail || e?.message || fallback
}
