import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Building2, ChevronDown, LogOut, Menu, X } from 'lucide-react'
import { useSession } from '../../session/SessionContext'
import { cn, initials } from '../../ui'
import { GlobalSearch } from './GlobalSearch'
import { visibleSections } from './navigation'

/**
 * Каркас приложения (TRU-80): боковое меню по ролям, шапка с поиском и
 * переключателем филиала, меню пользователя. Название раздела в шапке не
 * дублируем — заголовок один, в PageHeader страницы (TRU-89). На
 * экранах уже 1024px меню — выезжающая шторка.
 */
export default function Layout() {
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <div className="min-h-screen lg:pl-64">
      {/* Десктоп */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-line bg-surface lg:flex lg:flex-col">
        <Sidebar />
      </aside>

      {/* Телефон/планшет */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-surface shadow-pop">
            <button type="button" onClick={() => setDrawerOpen(false)} className="absolute right-3 top-4 rounded-md p-1.5 text-ink-subtle hover:bg-surface-muted" aria-label="Закрыть меню">
              <X className="size-5" />
            </button>
            {/* Переход по пункту меню закрывает шторку. */}
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <header className="sticky top-0 z-20 border-b border-line bg-canvas/85 backdrop-blur">
        <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
          <button type="button" onClick={() => setDrawerOpen(true)} className="-ml-1 rounded-md p-2 text-ink-muted hover:bg-surface-muted lg:hidden" aria-label="Меню">
            <Menu className="size-5" />
          </button>
          <GlobalSearch className="min-w-0 flex-1 md:max-w-lg" />
          <div className="ml-auto flex items-center gap-2">
            <BranchSwitcher />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:py-8">
        <Outlet />
      </main>
    </div>
  )
}

function Sidebar({ onNavigate }) {
  const { can } = useSession()
  return (
    <>
      <div className="flex h-16 items-center gap-2.5 px-5">
        <span className="flex size-9 items-center justify-center rounded-md bg-gradient-to-br from-brand-400 to-brand-600 text-white shadow-card">
          <svg viewBox="0 0 24 24" className="size-[18px]" fill="currentColor" aria-hidden="true">
            <path d="M12 2 2 7l10 5 10-5-10-5Zm-10 15 10 5 10-5M2 12l10 5 10-5" />
          </svg>
        </span>
        <span className="text-[17px] font-bold tracking-tight text-ink">KidsCRM</span>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        {visibleSections(can).map(section => (
          <div key={section.label}>
            <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">{section.label}</p>
            <ul className="space-y-0.5">
              {section.items.map(item => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    onClick={onNavigate}
                    className={({ isActive }) => cn(
                      'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                      isActive ? 'bg-brand-50 text-brand-700' : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
                    )}
                  >
                    <item.icon className="size-[18px]" />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <UserMenu />
    </>
  )
}

function UserMenu() {
  const { user, roleLabel, logout } = useSession()
  return (
    <div className="border-t border-line p-3">
      <div className="flex items-center gap-3 rounded-md px-2 py-2">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[13px] font-bold text-brand-700">
          {initials(user?.full_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">{user?.full_name}</p>
          <p className="truncate text-xs text-ink-muted">{roleLabel}</p>
        </div>
        <button type="button" onClick={logout} className="rounded-md p-2 text-ink-subtle hover:bg-surface-muted hover:text-ink" title="Выйти" aria-label="Выйти">
          <LogOut className="size-4" />
        </button>
      </div>
    </div>
  )
}

/**
 * Активный филиал: влияет на списки, которые умеют фильтровать по филиалу
 * (заголовок X-Branch-Id). Один филиал — переключать нечего, показываем просто название.
 */
function BranchSwitcher() {
  const { branches, activeBranch, activeBranchId, setActiveBranchId } = useSession()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onClick = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  if (!branches.length) return null
  const label = activeBranch?.name || 'Все филиалы'

  function choose(id) {
    setActiveBranchId(id)
    setOpen(false)
    // Списки на странице перечитают данные с новым заголовком.
    window.dispatchEvent(new CustomEvent('kc:branch-changed'))
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex h-10 max-w-[220px] items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm font-medium text-ink hover:border-line-strong"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <Building2 className="size-4 shrink-0 text-ink-subtle" />
        <span className="hidden truncate sm:inline">{label}</span>
        <ChevronDown className="size-4 shrink-0 text-ink-subtle" />
      </button>
      {open && (
        <ul className="absolute right-0 top-12 z-40 w-64 overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-pop" role="listbox">
          {[{ id: null, name: 'Все филиалы' }, ...branches].map(branch => (
            <li key={branch.id || 'all'}>
              <button
                type="button"
                role="option"
                aria-selected={String(branch.id) === String(activeBranchId)}
                onClick={() => choose(branch.id)}
                className={cn(
                  'w-full truncate px-4 py-2 text-left text-sm hover:bg-surface-muted',
                  (branch.id ? String(branch.id) === String(activeBranchId) : !activeBranchId) ? 'font-semibold text-brand-700' : 'text-ink',
                )}
              >
                {branch.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
