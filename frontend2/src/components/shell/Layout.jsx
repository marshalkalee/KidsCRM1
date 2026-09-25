import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Bell, Building2, ChevronDown, LogOut, Menu, PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import { useSession } from '../../session/SessionContext'
import { cn, initials } from '../../ui'
import { GlobalSearch } from './GlobalSearch'
import { visibleSections } from './navigation'

const COLLAPSED_KEY = 'kc:sidebar-collapsed'

function readCollapsed() {
  try { return localStorage.getItem(COLLAPSED_KEY) === '1' } catch { return false }
}

/**
 * Каркас приложения: боковое меню по ролям с пользователем внизу (на
 * компьютере сворачивается до иконок, выбор запоминается), шапка — поиск,
 * переключатель филиала, уведомления. Название раздела в шапке
 * не дублируем — заголовок один, в PageHeader страницы (TRU-89). На
 * экранах уже 1024px меню — выезжающая шторка.
 */
export default function Layout() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)

  function toggleCollapsed() {
    setCollapsed(value => {
      try { localStorage.setItem(COLLAPSED_KEY, value ? '0' : '1') } catch { /* приватный режим */ }
      return !value
    })
  }

  return (
    <div className={cn('min-h-screen transition-[padding] duration-200', collapsed ? 'lg:pl-[76px]' : 'lg:pl-64')}>
      {/* Десктоп */}
      <aside className={cn('fixed inset-y-0 left-0 z-30 hidden border-r border-line bg-surface transition-[width] duration-200 lg:flex lg:flex-col', collapsed ? 'w-[76px]' : 'w-64')}>
        <Sidebar collapsed={collapsed} />
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

      <header className="sticky top-0 z-20 border-b border-line bg-surface">
        <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
          <button type="button" onClick={() => setDrawerOpen(true)} className="-ml-1 rounded-md p-2 text-ink-muted hover:bg-surface-muted lg:hidden" aria-label="Меню">
            <Menu className="size-5" />
          </button>
          <button
            type="button"
            onClick={toggleCollapsed}
            className="-ml-2 hidden rounded-md p-2 text-ink-muted hover:bg-surface-muted hover:text-ink lg:block"
            aria-label={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
            title={collapsed ? 'Развернуть меню' : 'Свернуть меню'}
          >
            {collapsed ? <PanelLeftOpen className="size-5" /> : <PanelLeftClose className="size-5" />}
          </button>
          <GlobalSearch className="min-w-0 flex-1 md:max-w-md" />
          <div className="ml-auto flex items-center gap-2">
            <BranchSwitcher />
            <Notifications />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:py-8">
        <Outlet />
      </main>
    </div>
  )
}

function Sidebar({ onNavigate, collapsed = false }) {
  const { can } = useSession()
  return (
    <>
      <div className={cn('flex h-16 shrink-0 items-center gap-2.5 border-b border-line', collapsed ? 'justify-center' : 'px-5')}>
        <span className="bg-brand-gradient flex size-9 shrink-0 items-center justify-center rounded-[10px] text-white shadow-brand">
          <svg viewBox="0 0 24 24" className="size-[18px]" fill="currentColor" aria-hidden="true">
            <path d="M12 2 2 7l10 5 10-5-10-5Zm-10 15 10 5 10-5M2 12l10 5 10-5" />
          </svg>
        </span>
        {!collapsed && <span className="text-[17px] font-bold tracking-tight text-ink">KidsCRM</span>}
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {visibleSections(can).map(section => (
          <div key={section.label}>
            {collapsed
              ? <div className="mx-2 mb-2 h-px bg-line" aria-hidden="true" />
              : <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">{section.label}</p>}
            <ul className="space-y-0.5">
              {section.items.map(item => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    aria-label={collapsed ? item.label : undefined}
                    className={({ isActive }) => cn(
                      'relative flex items-center gap-3 rounded-[10px] py-2.5 text-sm transition-colors',
                      collapsed ? 'justify-center' : 'px-3',
                      isActive
                        ? 'bg-gradient-to-r from-brand-50 to-[#fff4ee] font-semibold text-brand-600 before:absolute before:-left-3 before:inset-y-2 before:w-[3px] before:rounded-r before:bg-brand-500'
                        : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
                    )}
                  >
                    <item.icon className="size-[18px] shrink-0" />
                    {!collapsed && item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <UserMenu collapsed={collapsed} />
    </>
  )
}

/** Всплывающее окно у кнопки в шапке: закрывается кликом мимо и Escape. */
function usePopover() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onDown = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  return { open, setOpen, ref }
}

/**
 * Колокольчик, как в шапке первого React. Серверной части уведомлений ещё
 * нет (domains/platform/notifications пустой) — поэтому честно «пока нет»,
 * без точки «есть новое».
 */
function Notifications() {
  const { open, setOpen, ref } = usePopover()
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex size-10 items-center justify-center rounded-[10px] border border-line bg-surface text-ink-muted hover:border-brand-300 hover:text-ink"
        aria-label="Уведомления"
        aria-expanded={open}
      >
        <Bell className="size-[18px]" />
      </button>
      {open && (
        <div className="absolute right-0 top-12 z-40 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-surface p-5 text-center shadow-pop">
          <span className="mx-auto mb-2 flex size-10 items-center justify-center rounded-full bg-brand-50 text-brand-500"><Bell className="size-5" /></span>
          <p className="text-sm font-semibold text-ink">Уведомлений пока нет</p>
          <p className="mt-1 text-[13px] text-ink-muted">Здесь будут напоминания о продлениях, долгах и занятиях.</p>
        </div>
      )}
    </div>
  )
}

/** Пользователь внизу меню: аватар, имя, роль и «Выйти» (свёрнутое меню — только аватар и выход). */
function UserMenu({ collapsed = false }) {
  const { user, roleLabel, logout } = useSession()
  return (
    <div className={cn('border-t border-line p-3', collapsed && 'flex flex-col items-center gap-1 px-2')}>
      <div className={cn('flex items-center gap-3 rounded-md py-2', collapsed ? 'justify-center px-0' : 'px-2')} title={collapsed ? `${user?.full_name} · ${roleLabel}` : undefined}>
        <span className="bg-brand-gradient flex size-9 shrink-0 items-center justify-center rounded-full text-[13px] font-bold text-white">
          {initials(user?.full_name)}
        </span>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-ink">{user?.full_name}</p>
            <p className="truncate text-xs text-ink-muted">{roleLabel}</p>
          </div>
        )}
        {!collapsed && (
          <button type="button" onClick={logout} className="rounded-md p-2 text-ink-subtle hover:bg-surface-muted hover:text-ink" title="Выйти" aria-label="Выйти">
            <LogOut className="size-4" />
          </button>
        )}
      </div>
      {collapsed && (
        <button type="button" onClick={logout} className="rounded-md p-2 text-ink-subtle hover:bg-surface-muted hover:text-ink" title="Выйти" aria-label="Выйти">
          <LogOut className="size-4" />
        </button>
      )}
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
        className="flex h-10 max-w-[220px] items-center gap-2 rounded-[10px] border border-line bg-surface px-3 text-sm font-medium text-ink hover:border-brand-300"
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
                  (branch.id ? String(branch.id) === String(activeBranchId) : !activeBranchId) ? 'bg-brand-50 font-semibold text-brand-600' : 'text-ink',
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
