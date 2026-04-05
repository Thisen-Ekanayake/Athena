import { Newspaper, Flame, Clock, Filter, List, Grid2X2 } from 'lucide-react'

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
  dateRange, setDateRange,
  viewMode, setViewMode
}: TopBarProps) {
  
  const categories = [
    { id: null, label: 'All Intelligence' },
    { id: 'paper', label: 'Papers' },
    { id: 'company_blog', label: 'Tech Blogs' },
    { id: 'community_blog', label: 'Community' }
  ]

  return (
    <div className="sticky top-0 z-20 glass-base border-b border-white/5 px-6 py-3 flex flex-col md:flex-row md:items-center justify-between gap-4 backdrop-blur-xl">
      
      {/* Category Pills */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2 md:pb-0 hide-scrollbar no-scrollbar">
        {categories.map(c => (
          <button
            key={c.id || 'all'}
            onClick={() => setCategory(c.id)}
            className={`whitespace-nowrap px-4 py-1.5 rounded-full text-[11px] font-display font-bold tracking-wider uppercase transition-all duration-300 ${
              category === c.id 
                ? 'bg-accent-primary text-white shadow-glow-primary' 
                : 'glass-void hover:glass-float text-text-muted hover:text-text-primary border border-white/5'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Controls Container */}
      <div className="flex items-center gap-3">
        {/* Date Filter */}
        <div className="relative group">
          <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none text-text-ghost">
            <Filter className="w-3 h-3" />
          </div>
          <select 
            value={dateRange}
            onChange={(e) => setDateRange(e.target.value as any)}
            className="appearance-none bg-void/40 border border-white/5 text-text-secondary text-[11px] font-bold rounded-lg pl-8 pr-8 py-2 focus:outline-none focus:border-accent-primary/50 cursor-pointer hover:bg-white/5 transition-all uppercase tracking-tight"
          >
            <option value="24h">Sort: 24H</option>
            <option value="7d">Sort: 7D</option>
            <option value="30d">Sort: 30D</option>
            <option value="all">Sort: INF</option>
          </select>
        </div>
        
        {/* Sort Switcher */}
        <div className="flex items-center glass-void rounded-lg p-1 border border-white/5">
          <button
            onClick={() => setSort('score')}
            className={`p-1.5 rounded-md transition-all duration-300 ${
              sort === 'score' ? 'bg-white/10 text-accent-primary shadow-sm' : 'text-text-muted hover:text-text-primary'
            }`}
            title="Relevance Score"
          >
            <Newspaper className="w-4 h-4" />
          </button>
          <button
            onClick={() => setSort('trending')}
            className={`p-1.5 rounded-md transition-all duration-300 ${
              sort === 'trending' ? 'bg-white/10 text-accent-tertiary shadow-sm' : 'text-text-muted hover:text-text-primary'
            }`}
            title="Social Signal"
          >
            <Flame className="w-4 h-4" />
          </button>
          <button
            onClick={() => setSort('date')}
            className={`p-1.5 rounded-md transition-all duration-300 ${
              sort === 'date' ? 'bg-white/10 text-accent-secondary shadow-sm' : 'text-text-muted hover:text-text-primary'
            }`}
            title="Recency"
          >
            <Clock className="w-4 h-4" />
          </button>
        </div>

        {/* View Mode Toggle */}
        <div className="flex items-center glass-void rounded-lg p-1 border border-white/5">
          <button
            onClick={() => setViewMode('expanded')}
            className={`p-1.5 rounded-md transition-all duration-300 ${
              viewMode === 'expanded' ? 'bg-white/10 text-white shadow-sm' : 'text-text-muted hover:text-text-primary'
            }`}
            title="Expanded View"
          >
            <List className="w-4 h-4" />
          </button>
          <button
            onClick={() => setViewMode('compact')}
            className={`p-1.5 rounded-md transition-all duration-300 ${
              viewMode === 'compact' ? 'bg-white/10 text-white shadow-sm' : 'text-text-muted hover:text-text-primary'
            }`}
            title="Compact View"
          >
            <Grid2X2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

