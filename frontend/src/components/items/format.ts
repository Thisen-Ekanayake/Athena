import { formatDistanceToNowStrict } from 'date-fns'

export const CATEGORY_LABELS: Record<string, string> = {
  paper: 'Paper',
  company_blog: 'Lab blog',
  community_blog: 'Community',
}

/** "3 hours ago", or an empty string for a missing or unparsable date. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : formatDistanceToNowStrict(d, { addSuffix: true })
}

export function formatScore(score: number | null | undefined): string {
  return typeof score === 'number' ? score.toFixed(2) : '—'
}
