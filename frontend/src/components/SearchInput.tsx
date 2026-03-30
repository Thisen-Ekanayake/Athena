import { useState, useEffect } from 'react'
import { Search as SearchIcon, X, Command } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

interface SearchInputProps {
  isCondensed?: boolean
}

export function SearchInput({ isCondensed }: SearchInputProps) {
  const [query, setQuery] = useState('')
  const [isFocused, setIsFocused] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.length > 2) {
        navigate(`/search?q=${encodeURIComponent(query)}`)
      } else if (query.length === 0 && window.location.pathname === '/search') {
        navigate('/')
      }
    }, 400)
    return () => clearTimeout(timer)
  }, [query, navigate])

  if (isCondensed) {
    return (
      <button 
        className="w-full flex items-center justify-center p-2 rounded-md transition-all duration-300 text-text-muted hover:text-accent-primary hover:bg-white/5"
        onClick={() => setIsFocused(true)}
      >
        <SearchIcon className="w-[18px] h-[18px]" />
      </button>
    )
  }

  return (
    <div className="relative group w-full">
      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
        <SearchIcon className={`h-4 w-4 transition-colors duration-300 ${isFocused ? 'text-accent-primary' : 'text-text-muted'}`} />
      </div>
      <input
        type="text"
        placeholder="Search..."
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        className="block w-full pl-10 pr-12 py-2 border border-border-subtle rounded-md text-[13px] bg-glass-fill backdrop-blur-glass text-text-primary placeholder-text-muted focus:outline-none focus:border-border-glow focus:ring-1 focus:ring-accent-primary/20 transition-all duration-300"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      
      <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
        {query.length === 0 ? (
          <div className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-border-subtle bg-white/5 text-[10px] font-mono text-text-ghost transition-opacity duration-300 ${isFocused ? 'opacity-0' : 'opacity-100'}`}>
            <Command className="w-2.5 h-2.5" />
            <span>K</span>
          </div>
        ) : (
          <button 
            onClick={() => setQuery('')}
            className="pointer-events-auto text-text-muted hover:text-text-primary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  )
}

