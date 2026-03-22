import { Newspaper, Flame, Clock } from 'lucide-react'

interface TopBarProps {
  sort: 'score' | 'date' | 'trending'
  setSort: (s: 'score' | 'date' | 'trending') => void
  category: string | null
  setCategory: (c: string | null) => void
  dateRange: '24h' | '7d' | '30d' | 'all'
  setDateRange: (r: '24h' | '7d' | '30d' | 'all') => void
  viewMode: 'compact' | 'expanded'
  setViewMode: (v: 'compact' | 'expanded') => void
}

export function FeedTopBar({ 
  sort, setSort, 
  category, setCategory,
  dateRange, setDateRange
}: TopBarProps) {
  
  const categories = [
    { id: null, label: 'All' },
    { id: 'paper', label: 'Papers' },
    { id: 'company_blog', label: 'Company Blogs' },
    { id: 'community_blog', label: 'Community Blogs' }
  ]

  return (
    <div className="sticky top-0 z-10 bg-background/80 backdrop-blur-md border-b border-border px-6 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      
      {/* Category Pills */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2 sm:pb-0 hide-scrollbar">
        {categories.map(c => (
          <button
            key={c.id || 'all'}
            onClick={() => setCategory(c.id)}
            aria-label={`Filter by ${c.label}`}
            aria-pressed={category === c.id}
            className={`whitespace-nowrap px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              category === c.id 
                ? 'bg-white text-black' 
                : 'bg-zinc-800/50 text-zinc-400 hover:bg-zinc-800 hover:text-white'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Sort controls */}
      <div className="flex items-center gap-3">
        <select 
          value={dateRange}
          onChange={(e) => setDateRange(e.target.value as any)}
          aria-label="Filter by date range"
          className="bg-zinc-900 border border-border text-zinc-300 text-xs rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-accentPrimary"
        >
          <option value="24h">Past 24 Hours</option>
          <option value="7d">Past Week</option>
          <option value="30d">Past Month</option>
          <option value="all">All Time</option>
        </select>
        
        <div className="flex items-center bg-zinc-900 rounded-lg p-1 border border-border" role="group" aria-label="Sort feed">
          <button
            onClick={() => setSort('score')}
            aria-pressed={sort === 'score'}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              sort === 'score' ? 'bg-zinc-700 text-white shadow' : 'text-zinc-400 hover:text-white'
            }`}
          >
            <Newspaper className="w-3.5 h-3.5" />
            Top
          </button>
          <button
            onClick={() => setSort('trending')}
            aria-pressed={sort === 'trending'}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              sort === 'trending' ? 'bg-zinc-700 text-white shadow' : 'text-zinc-400 hover:text-white'
            }`}
          >
            <Flame className="w-3.5 h-3.5" />
            Trending
          </button>
          <button
            onClick={() => setSort('date')}
            aria-pressed={sort === 'date'}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              sort === 'date' ? 'bg-zinc-700 text-white shadow' : 'text-zinc-400 hover:text-white'
            }`}
          >
            <Clock className="w-3.5 h-3.5" />
            Latest
          </button>
        </div>
      </div>
    </div>
  )
}
