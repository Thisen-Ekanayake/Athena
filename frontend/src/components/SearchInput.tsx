
import { useState, useEffect } from 'react'
import { Search as SearchIcon, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export function SearchInput() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.length > 2) {
        navigate(`/search?q=${encodeURIComponent(query)}`)
      } else if (query.length === 0 && window.location.pathname === '/search') {
        navigate('/')
      }
    }, 400) // 400ms debounce
    return () => clearTimeout(timer)
  }, [query, navigate])

  return (
    <div className="relative group flex-1 max-w-sm">
      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
        <SearchIcon className="h-4 w-4 text-zinc-500 group-focus-within:text-accentPrimary transition-colors" />
      </div>
      <input
        type="text"
        placeholder="Search semantic concepts..."
        className="block w-full pl-10 pr-10 py-2 border border-zinc-700 rounded-md leading-5 bg-zinc-900/50 text-zinc-300 placeholder-zinc-500 focus:outline-none focus:bg-zinc-900 focus:border-accentPrimary focus:ring-1 focus:ring-accentPrimary sm:text-sm transition-all shadow-sm"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {query.length > 0 && (
        <button 
          onClick={() => setQuery('')}
          className="absolute inset-y-0 right-0 pr-3 flex items-center text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
