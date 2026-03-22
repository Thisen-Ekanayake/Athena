

export function CardSkeleton() {
  return (
    <div className="card p-5 flex flex-col gap-3 animate-pulse">
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-2 w-1/2">
          <div className="h-4 bg-zinc-800 rounded w-24"></div>
          <div className="h-4 bg-zinc-800 rounded w-4"></div>
          <div className="h-4 bg-zinc-800 rounded w-16"></div>
        </div>
        <div className="h-6 bg-zinc-800 rounded w-12"></div>
      </div>
      
      <div className="h-6 bg-zinc-800 rounded w-3/4 mt-2"></div>
      <div className="h-6 bg-zinc-800 rounded w-1/2"></div>
      
      <div className="space-y-2 mt-4">
        <div className="h-3 bg-zinc-800 rounded"></div>
        <div className="h-3 bg-zinc-800 rounded w-5/6"></div>
        <div className="h-3 bg-zinc-800 rounded w-4/6"></div>
      </div>
      
      <div className="mt-4 pt-4 border-t border-zinc-800/50 flex gap-4">
        <div className="h-4 bg-zinc-800 rounded w-24"></div>
        <div className="h-4 bg-zinc-800 rounded w-16"></div>
      </div>
    </div>
  )
}
