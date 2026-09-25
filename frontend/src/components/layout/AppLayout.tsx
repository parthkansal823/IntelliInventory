import {
  CircleHelp,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Search,
  Sun,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { useApprovals, useAlerts } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useLiveEvents } from '@/hooks/useLiveEvents'
import { useTheme, type Theme } from '@/hooks/useTheme'
import { usePublicConfig } from '@/hooks/usePublicConfig'
import { cn } from '@/lib/utils'
import { Kbd, Tooltip } from '../ui'
import { LangToggle, Onboarding, openTutorial } from '../Onboarding'
import { CommandPalette } from './CommandPalette'
import { NAV } from './nav'
import { useT } from '@/lib/i18n'


function Brand() {
  const t = useT()
  return (
    <div className="flex items-center gap-2.5 px-2">
      <img src="/favicon.svg" alt="" className="size-8 rounded-lg" />
      <div className="leading-tight">
        <div className="text-sm font-semibold">{t('IntelliInventory')}</div>
        <div className="text-[11px] text-muted">{t('AI-native inventory')}</div>
      </div>
    </div>
  )
}

function ThemeSwitch() {
  const t = useT()
  const { theme, setTheme } = useTheme()
  const order: Theme[] = ['light', 'dark', 'system']
  const Icon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor
  return (
    <Tooltip content={`Theme: ${theme}`}>
      <button
        onClick={() => setTheme(order[(order.indexOf(theme) + 1) % order.length])}
        className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg"
        aria-label={t('Toggle theme')}
      >
        <Icon className="size-4" />
      </button>
    </Tooltip>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const t = useT()
  const { user, logout } = useAuth()
  const approvals = useApprovals()
  const alerts = useAlerts()
  const pending = approvals.data?.length ?? 0
  const critical = alerts.data?.filter((a) => a.severity === 'critical').length ?? 0
  const badges: Record<string, number> = { '/copilot': pending, '/': critical }

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="pt-2">
        <Brand />
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto">
        {NAV.map(({ to, label, icon: Icon, section }, i) => (
          <div key={to}>
            {section !== NAV[i - 1]?.section && <div className="px-2.5 pt-3 pb-1 text-[11px] font-medium tracking-wide text-subtle uppercase">{t(section)}</div>}
            <NavLink
              to={to}
              end={to === '/'}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition',
                  isActive ? 'bg-brand-soft text-brand' : 'text-muted hover:bg-surface-2 hover:text-fg',
                )
              }
            >
              <Icon className="size-4" />
              <span className="flex-1">{t(label)}</span>
              {badges[to] ? (
                <span className={cn('rounded-full px-1.5 text-[10px] font-semibold text-white', to === '/copilot' ? 'bg-brand' : 'bg-critical')}>{badges[to]}</span>
              ) : null}
            </NavLink>
          </div>
        ))}
      </nav>
      <div className="rounded-xl border border-border bg-surface p-3">
        <div className="flex items-center gap-2.5">
          <div className="grid size-8 place-items-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
            {user?.name.split(' ').map((p) => p[0]).join('').slice(0, 2)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user?.name}</div>
            <div className="text-[11px] capitalize text-muted">{user?.role}</div>
          </div>
          <Tooltip content={t('Sign out')}>
            <button onClick={logout} className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg" aria-label={t('Sign out')}>
              <LogOut className="size-4" />
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  )
}

export function AppLayout() {
  const t = useT()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const { connected } = useLiveEvents()
  const config = usePublicConfig()
  const navigate = useNavigate()
  const location = useLocation()

  // Keyboard: ⌘K / Ctrl-K palette, "/" search, "g" + key to jump between pages.
  useEffect(() => {
    let leader = false
    let timer: number | undefined
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
        return
      }
      if (typing) return
      if (e.key === '/') {
        e.preventDefault()
        setPaletteOpen(true)
      } else if (e.key === 'g') {
        leader = true
        window.clearTimeout(timer)
        timer = window.setTimeout(() => (leader = false), 900)
      } else if (leader) {
        const item = NAV.find((n) => n.key === e.key)
        if (item) navigate(item.to)
        leader = false
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])

  useEffect(() => setMobileOpen(false), [location.pathname])
  const current = NAV.find((n) => (n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)))

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-border bg-bg lg:block">
        <Sidebar />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-border bg-bg animate-fade-in">
            <button className="absolute top-4 right-3 p-1 text-muted" onClick={() => setMobileOpen(false)} aria-label={t('Close menu')}>
              <X className="size-4" />
            </button>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-bg/80 px-4 backdrop-blur lg:px-6">
          <button className="rounded-lg p-2 text-muted hover:bg-surface-2 lg:hidden" onClick={() => setMobileOpen(true)} aria-label={t('Open menu')}>
            <Menu className="size-5" />
          </button>
          <div className="text-sm font-medium text-muted lg:hidden">{current ? t(current.label) : null}</div>
          <button
            onClick={() => setPaletteOpen(true)}
            className="ml-auto flex h-9 w-full max-w-md items-center gap-2 rounded-lg border border-border bg-surface px-3 text-sm text-subtle transition hover:border-brand/40 lg:ml-0"
          >
            <Search className="size-4" />
            <span className="hidden flex-1 truncate text-left sm:block">{t('Search products, pages, or ask Copilot…')}</span>
            <span className="flex-1 text-left sm:hidden">{t('Search…')}</span>
            <span className="hidden sm:inline"><Kbd>⌘K</Kbd></span>
          </button>
          <div className="ml-auto flex items-center gap-1">
            {config.data?.demo_mode && (
              <Tooltip content={t('Public demo — sample data, resets periodically')}>
                <span className="rounded-md border border-warning/40 bg-warning/15 px-2 py-0.5 text-xs font-medium text-[#8a5a00] dark:text-warning">{t('Demo')}</span>
              </Tooltip>
            )}
            <Tooltip content={connected ? 'Live updates connected' : 'Reconnecting…'}>
              <span className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted">
                <span className={cn('size-2 rounded-full', connected ? 'bg-good animate-pulse-dot' : 'bg-subtle')} />
                <span className="hidden sm:inline">{connected ? 'Live' : 'Offline'}</span>
              </span>
            </Tooltip>
            <LangToggle />
            <Tooltip content={t('Help & tutorial')}>
              <button onClick={openTutorial} className="rounded-lg p-2 text-muted hover:bg-surface-2 hover:text-fg" aria-label={t('Help & tutorial')}>
                <CircleHelp className="size-4" />
              </button>
            </Tooltip>
            <ThemeSwitch />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-6">
            <Outlet />
          </div>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <Onboarding />
    </div>
  )
}
