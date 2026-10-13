const compactFormat = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })

/** 1,284 -> 1.3K; 12_900_000 -> 12.9M. */
export const compact = (n: number) => compactFormat.format(n)

/** Dollars, with more places for the fractions of a cent hosted models charge per call. */
export function usd(n: number) {
  if (!n) return '$0'
  return n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** "October", from "2026-10". */
export const monthName = (month: string) =>
  new Date(`${month}-01T00:00:00Z`).toLocaleDateString(undefined, { month: 'long', timeZone: 'UTC' })

/** "1 November", from the reset time the API sends. */
export const resetDay = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'long', timeZone: 'UTC' })
