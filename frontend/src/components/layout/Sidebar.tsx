import { Link, NavLink } from 'react-router-dom'
import { Bookmark, GitBranch, House, Layers, Newspaper, Settings, TrendingUp, type LucideIcon } from 'lucide-react'
import { useAppStore, type Accent } from '../../store/appStore'
import { OwlCoin } from '../../ui/OwlCoin'
import { cn } from '../../ui/cn'

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: '/', label: 'Home', icon: House, end: true },
  { to: '/feed', label: 'Feed', icon: Newspaper },
  { to: '/trending', label: 'Trending', icon: TrendingUp },
  { to: '/clusters', label: 'Clusters', icon: Layers },
  { to: '/evolution', label: 'Evolution', icon: GitBranch },
  { to: '/saved', label: 'Saved', icon: Bookmark },
]

const ACCENTS: { value: Accent; label: string; swatch: string }[] = [
  { value: 'gold', label: 'Gold', swatch: '#C49A4A' },
  { value: 'indigo', label: 'Indigo', swatch: '#6B6BE0' },
]

function Item({ to, label, icon: Icon, end, compact, onNavigate }: { to: string; label: string; icon: LucideIcon; end?: boolean; compact: boolean; onNavigate?: () => void }) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      title={label}
      className={({ isActive }) =>
        cn(
          'flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] transition-colors',
          compact && 'lg:justify-start max-lg:justify-center max-lg:px-0',
          isActive ? 'bg-surface-2 text-fg shadow-[0_0_0_1px_var(--line)]' : 'text-fg-2 hover:bg-surface-2/70 hover:text-fg',
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className={cn(compact && 'max-lg:sr-only')}>{label}</span>
    </NavLink>
  )
}

/**
 * The app's navigation. On desktop it narrows to icons below 1024px; on phones the same
 * content opens as a sheet (`compact={false}`).
 */
export function Sidebar({ compact = true, onNavigate, className }: { compact?: boolean; onNavigate?: () => void; className?: string }) {
  const accent = useAppStore((s) => s.accent)
  const setAccent = useAppStore((s) => s.setAccent)

  return (
    <aside className={cn('flex flex-col gap-5 px-3 py-4', compact && 'sticky top-0 h-screen w-[220px] shrink-0 border-r border-line max-lg:w-[60px] max-lg:px-2', className)}>
      <Link to="/" onClick={onNavigate} className={cn('flex h-8 items-center gap-2.5 px-2', compact && 'max-lg:justify-center max-lg:px-0')}>
        <OwlCoin size={26} />
        <span className={cn('text-[15px] font-semibold tracking-[-0.01em]', compact && 'max-lg:sr-only')}>Athena</span>
      </Link>
      <nav className="grid gap-0.5" aria-label="Main">
        {NAV.map((n) => <Item key={n.to} {...n} compact={compact} onNavigate={onNavigate} />)}
      </nav>
      <div className="mt-auto grid gap-2">
        <div role="group" aria-label="Accent colour" className={cn('flex items-center gap-1.5 px-2.5', compact && 'max-lg:flex-col max-lg:px-0')}>
          <span className={cn('mr-auto text-[12px] text-fg-3', compact && 'max-lg:sr-only')}>Look</span>
          {ACCENTS.map((a) => (
            <button
              key={a.value}
              type="button"
              onClick={() => setAccent(a.value)}
              aria-pressed={accent === a.value}
              title={a.label}
              className={cn('flex h-6 w-6 items-center justify-center rounded-full border transition-colors', accent === a.value ? 'border-fg-3' : 'border-transparent hover:border-line-strong')}
            >
              <span className="h-3 w-3 rounded-full" style={{ background: a.swatch }} />
              <span className="sr-only">{a.label}</span>
            </button>
          ))}
        </div>
        <Item to="/settings" label="Settings" icon={Settings} compact={compact} onNavigate={onNavigate} />
      </div>
    </aside>
  )
}
