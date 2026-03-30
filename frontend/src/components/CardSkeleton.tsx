export function CardSkeleton() {
  return (
    <div className="glass-base rounded-2xl p-6 flex flex-col gap-4 animate-pulse border border-white/5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3 w-1/2">
          <div className="w-10 h-10 rounded-full bg-white/5"></div>
          <div className="space-y-2 flex-1">
            <div className="h-2 bg-white/5 rounded w-24"></div>
            <div className="h-3 bg-white/10 rounded w-32"></div>
          </div>
        </div>
        <div className="w-10 h-10 rounded-full bg-white/5"></div>
      </div>
      
      <div className="h-6 bg-white/10 rounded-lg w-3/4 mt-2"></div>
      <div className="h-6 bg-white/10 rounded-lg w-1/2"></div>
      
      <div className="space-y-2 mt-4 flex-1">
        <div className="h-2.5 bg-white/5 rounded w-full"></div>
        <div className="h-2.5 bg-white/5 rounded w-5/6"></div>
        <div className="h-2.5 bg-white/5 rounded w-4/6"></div>
      </div>
      
      <div className="mt-4 pt-4 border-t border-white/5 flex gap-4">
        <div className="h-3 bg-white/5 rounded w-20"></div>
        <div className="h-3 bg-white/5 rounded w-16"></div>
      </div>
    </div>
  )
}

