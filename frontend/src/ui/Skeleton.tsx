import { cn } from './cn'

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-surface-2', className)} />
}

/** Placeholder rows shaped like item rows, for lists that are still loading. */
export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="grid gap-2 bg-surface px-4 py-3.5">
          <Skeleton className="h-3.5 w-3/4" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      ))}
    </div>
  )
}
