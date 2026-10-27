import { useState } from 'react'
import { Link, NavLink, useMatch, useNavigate } from 'react-router-dom'
import {
  ChevronRight, FolderKanban, GitBranch, House, Layers, Library, LogOut, MessageSquare, Newspaper, Pin, Settings, SquarePen,
  TrendingUp, type LucideIcon,
} from 'lucide-react'
import { useCurrentUser, useLogout } from '../../api/queries/auth'
import { useChats, type ChatSummary } from '../../api/queries/chats'
import { useProjects } from '../../api/queries/projects'
import { useChatStreams } from '../../store/chatStore'
import { useAppStore, type Accent } from '../../store/appStore'
import { Button } from '../../ui/Button'
import { MarqueeText } from '../../ui/MarqueeText'
import { OwlCoin } from '../../ui/OwlCoin'
import { cn } from '../../ui/cn'
import { ChatActions, HIDE_ON_HOVER, RenameField, SHOW_ON_HOVER } from '../../features/chat/ChatActions'
import { SyncPanel } from './SyncPanel'

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: '/', label: 'Home', icon: House, end: true },
  { to: '/feed', label: 'Feed', icon: Newspaper },
  { to: '/rising', label: 'Rising', icon: TrendingUp },
  { to: '/clusters', label: 'Clusters', icon: Layers },
  { to: '/evolution', label: 'Evolution', icon: GitBranch },
  { to: '/library', label: 'Library', icon: Library },
]

const RECENT_CHATS = 6

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

const subRow = (active: boolean) =>
  cn('group flex h-7 items-center rounded-md text-[12.5px] transition-colors', active ? 'bg-surface-2 text-fg' : 'text-fg-3 hover:bg-surface-2/70 hover:text-fg-2')

/** The Projects link, with a chevron that lists the projects under it. The choice is remembered. */
function ProjectsNav({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const open = useAppStore((s) => s.projectsOpen)
  const setOpen = useAppStore((s) => s.setProjectsOpen)
  const projects = useProjects()
  return (
    <>
      <div className="relative">
        <Item to="/projects" label="Projects" icon={FolderKanban} end={open} compact={compact} onNavigate={onNavigate} />
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls="sidebar-projects"
          aria-label={open ? 'Hide projects' : 'Show projects'}
          title={open ? 'Hide projects' : 'Show projects'}
          className={cn('absolute top-1/2 right-1 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-fg-3 hover:bg-surface-2 hover:text-fg', compact && 'max-lg:hidden')}
        >
          <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} aria-hidden="true" />
        </button>
      </div>
      {open && (
        <ul id="sidebar-projects" className={cn('grid grid-cols-1 gap-px pl-[26px]', compact && 'max-lg:hidden')} aria-label="Projects">
          {projects.data?.length ? projects.data.map((p) => <ProjectRow key={p.id} id={p.id} name={p.name} onNavigate={onNavigate} />) : (
            <li className="flex h-7 items-center px-2 text-[12.5px] text-fg-3">{projects.isLoading ? 'Loading…' : 'No projects yet'}</li>
          )}
        </ul>
      )}
    </>
  )
}

function ProjectRow({ id, name, onNavigate }: { id: string; name: string; onNavigate?: () => void }) {
  const [hover, setHover] = useState(false)
  const active = !!useMatch(`/projects/${id}`)
  return (
    <li onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <NavLink to={`/projects/${id}`} onClick={onNavigate} className={cn(subRow(active), 'px-2')}>
        <MarqueeText text={name} active={hover} className="min-w-0 flex-1" />
      </NavLink>
    </li>
  )
}

/** The Chats link, with a chevron that lists the latest chats under it (hidden until opened). The choice is remembered. */
function ChatsNav({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const open = useAppStore((s) => s.chatsOpen)
  const setOpen = useAppStore((s) => s.setChatsOpen)
  return (
    <>
      <div className="relative">
        <Item to="/chats" label="Chats" icon={MessageSquare} end compact={compact} onNavigate={onNavigate} />
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls="sidebar-chats"
          aria-label={open ? 'Hide chats' : 'Show chats'}
          title={open ? 'Hide chats' : 'Show chats'}
          className={cn('absolute top-1/2 right-1 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-fg-3 hover:bg-surface-2 hover:text-fg', compact && 'max-lg:hidden')}
        >
          <ChevronRight className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} aria-hidden="true" />
        </button>
      </div>
      {open && <RecentChats compact={compact} onNavigate={onNavigate} />}
    </>
  )
}

/** The latest chats under the Chats link, pinned first; one being answered shows a pulse. Hidden when the sidebar is icons. */
function RecentChats({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const chats = useChats({ limit: RECENT_CHATS })
  const drafts = useChatStreams((s) => s.drafts)
  if (!chats.data?.length) {
    return <p id="sidebar-chats" className={cn('flex h-7 items-center pl-[34px] text-[12.5px] text-fg-3', compact && 'max-lg:hidden')}>{chats.isLoading ? 'Loading…' : 'No chats yet'}</p>
  }
  return (
    <ul id="sidebar-chats" className={cn('grid grid-cols-1 gap-px pl-[26px]', compact && 'max-lg:hidden')} aria-label="Recent chats">
      {chats.data.map((c) => <ChatRow key={c.id} chat={c} streaming={!!drafts[c.id]?.streaming} onNavigate={onNavigate} />)}
    </ul>
  )
}

/**
 * One chat in the sidebar. Hovered, its title scrolls when too long and it shows a menu (rename, archive, delete) and
 * a pin. A pinned chat keeps a small pin.
 */
function ChatRow({ chat, streaming, onNavigate }: { chat: ChatSummary; streaming: boolean; onNavigate?: () => void }) {
  const [hover, setHover] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const active = !!useMatch(`/chats/${chat.id}`)
  const navigate = useNavigate()

  if (renaming) {
    return <li><RenameField chat={chat} onDone={() => setRenaming(false)} className="h-7 text-[12.5px]" /></li>
  }
  return (
    <li onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} className={subRow(active)}>
      <NavLink to={`/chats/${chat.id}`} onClick={onNavigate} className="flex h-full min-w-0 flex-1 items-center gap-1.5 pr-1 pl-2">
        <MarqueeText text={chat.title} active={hover} className="min-w-0 flex-1" />
        {streaming && <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent" aria-label="Answering" />}
        {chat.pinned && <Pin className={cn('h-3 w-3 shrink-0 text-fg-3', HIDE_ON_HOVER)} aria-label="Pinned" />}
      </NavLink>
      <div className={cn('shrink-0 items-center pr-0.5', SHOW_ON_HOVER)}>
        <ChatActions chat={chat} onRename={() => setRenaming(true)} onDeleted={() => active && navigate('/chats')} />
      </div>
    </li>
  )
}

/** Who is logged in, with a way out. The name links to the Account settings. */
function UserMenu({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const user = useCurrentUser()
  const logout = useLogout()
  const navigate = useNavigate()
  if (!user) return null
  const initial = (user.display_name || user.email).trim().charAt(0).toUpperCase()
  return (
    <div className={cn('flex items-center gap-1', compact && 'max-lg:flex-col')}>
      <Link
        to="/settings/account"
        onClick={onNavigate}
        title={`${user.display_name} (${user.email})`}
        className={cn('flex h-8 min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2 text-fg-2 hover:bg-surface-2/70 hover:text-fg', compact && 'max-lg:justify-center max-lg:px-0')}
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[11px] font-medium text-fg shadow-[0_0_0_1px_var(--line)]" aria-hidden="true">{initial}</span>
        <span className={cn('min-w-0 truncate text-[13px]', compact && 'max-lg:sr-only')}>{user.display_name}</span>
      </Link>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })}
        disabled={logout.isPending}
        aria-label="Log out"
        title="Log out"
      >
        <LogOut />
      </Button>
    </div>
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
      <Link
        to="/chats/new"
        onClick={onNavigate}
        title="New chat"
        className={cn('-mt-2 flex h-8 items-center gap-2.5 rounded-lg border border-line bg-surface px-2.5 text-[13.5px] text-fg transition-colors hover:border-line-strong hover:bg-surface-2', compact && 'max-lg:justify-center max-lg:px-0')}
      >
        <SquarePen className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <span className={cn(compact && 'max-lg:sr-only')}>New chat</span>
      </Link>
      <nav className="grid gap-0.5" aria-label="Main">
        {NAV.map((n) => <Item key={n.to} {...n} compact={compact} onNavigate={onNavigate} />)}
      </nav>
      {/* Scrolls when the lists are long, without a scrollbar */}
      <nav
        className="-mt-2 grid min-h-0 grid-cols-1 content-start gap-0.5 overflow-x-hidden overflow-y-auto border-t border-line pt-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        aria-label="Your work"
      >
        <ProjectsNav compact={compact} onNavigate={onNavigate} />
        <ChatsNav compact={compact} onNavigate={onNavigate} />
      </nav>
      <div className="mt-auto grid min-w-0 grid-cols-1 gap-2">
        <SyncPanel compact={compact} />
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
        <UserMenu compact={compact} onNavigate={onNavigate} />
      </div>
    </aside>
  )
}
