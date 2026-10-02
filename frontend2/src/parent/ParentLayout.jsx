import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import {
  Check,
  ChevronDown,
  CloudOff,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { Bell, Check, ChevronDown, CloudOff } from 'lucide-react'
import { Avatar, Modal, cn, formatDateTime } from '../ui'
import { t, useLang } from '../i18n'
import { useParent } from './useParent'
import { usePortalData } from './api'
import { installPwa } from './pwa'
import { PARENT_NAV } from './nav'

const COLLAPSED_KEY = 'kc:parent-sidebar-collapsed'

function readCollapsed() {
  try { return localStorage.getItem(COLLAPSED_KEY) === '1' } catch { return false }
}

function useOnline() {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])
  return online
}

/**
 * На компьютере кабинет выглядит как CRM: боковое меню, шапка и широкая
 * рабочая область. На телефоне — компактная шапка и пять вкладок снизу.
 * Сессия остаётся родительской: служебные API и разделы недоступны даже по URL.
 */
export default function ParentLayout() {
  useLang()
  const { child, children, me } = useParent()
  const [picking, setPicking] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const online = useOnline()

  useEffect(() => { installPwa() }, [])

  function toggleCollapsed() {
    setCollapsed(value => {
      try { localStorage.setItem(COLLAPSED_KEY, value ? '0' : '1') } catch { /* приватный режим */ }
      return !value
    })
  }

  return (
    <div className={cn(
      'min-h-dvh bg-canvas pb-[calc(4.5rem+env(safe-area-inset-bottom))] transition-[padding] duration-200 lg:pb-0',
      collapsed ? 'lg:pl-[76px]' : 'lg:pl-64',
    )}>
      <aside className={cn(
        'fixed inset-y-0 left-0 z-30 hidden border-r border-line bg-surface transition-[width] duration-200 lg:flex lg:flex-col',
        collapsed ? 'w-[76px]' : 'w-64',
      )}>
        <ParentSidebar collapsed={collapsed} />
      </aside>

      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-[1500px] items-center gap-3 px-4 sm:px-6 lg:max-w-none">
          <Link to="/parent" className="rounded-[10px] outline-none focus-visible:ring-2 focus-visible:ring-brand-400 lg:hidden" aria-label={t('Главная')}>
            <BrandMark />
          </Link>
          <button
            type="button"
            onClick={toggleCollapsed}
            className="-ml-2 hidden rounded-md p-2 text-ink-muted hover:bg-surface-muted hover:text-ink lg:block"
            aria-label={collapsed ? t('Развернуть меню') : t('Свернуть меню')}
            title={collapsed ? t('Развернуть меню') : t('Свернуть меню')}
          >
            {collapsed ? <PanelLeftOpen className="size-5" /> : <PanelLeftClose className="size-5" />}
          </button>

          <ChildButton child={child} childOptions={children} onPick={() => setPicking(true)} />
        <div className="mx-auto flex h-14 max-w-2xl items-center gap-3 px-4">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-[linear-gradient(135deg,#ff9d8a,#e4586e)] text-[11px] font-bold text-white">KC</span>
          {child ? (
            <button
              type="button"
              onClick={() => children.length > 1 && setPicking(true)}
              className={cn('flex min-w-0 flex-1 items-center gap-2 rounded-lg py-1 text-left', children.length > 1 && 'hover:bg-canvas')}
              aria-label={children.length > 1 ? t('Выбрать ребёнка') : undefined}
            >
              <Avatar name={child.full_name} src={child.photo_url} />
              <span className="min-w-0">
                <span className="block truncate text-[15px] font-bold text-ink">{child.full_name}</span>
                <span className="block truncate text-[12px] text-ink-muted">{child.organization.name}</span>
              </span>
              {children.length > 1 && <ChevronDown className="size-4 shrink-0 text-ink-muted" />}
            </button>
          ) : (
            <span className="flex-1 text-[15px] font-bold text-ink">{t('Кабинет родителя')}</span>
          )}
          <NewsBell />
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        {(!online || me.stale) && (
          <p role="status" className="mb-4 flex items-center gap-2 rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-warning-600">
            <CloudOff className="size-4 shrink-0" />
            {me.savedAt
              ? t('Нет связи. Показаны данные от {time} — могут быть неактуальны.', { time: formatDateTime(me.savedAt) })
              : t('Нет связи. Данные могут быть неактуальны.')}
          </p>
        )}
        <Outlet />
      </main>

      <nav aria-label={t('Разделы кабинета')} className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        <div className="mx-auto grid max-w-2xl grid-cols-5">
          {PARENT_NAV.filter(item => item.mobile !== false).map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => cn(
                'flex h-16 min-w-0 flex-col items-center justify-center gap-1 text-[10px] font-semibold sm:text-[11px]',
                isActive ? 'text-brand-600' : 'text-ink-muted',
              )}
            >
              <item.icon className="size-5 shrink-0" />
              <span className="max-w-full truncate px-1">{item.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>

      {picking && <ChildPicker onClose={() => setPicking(false)} />}
    </div>
  )
}

function BrandMark({ className }) {
  return (
    <span className={cn('bg-brand-gradient flex size-9 shrink-0 items-center justify-center rounded-[10px] text-white shadow-brand', className)}>
      <svg viewBox="0 0 24 24" className="size-[18px]" fill="currentColor" aria-hidden="true">
        <path d="M12 2 2 7l10 5 10-5-10-5Zm-10 15 10 5 10-5M2 12l10 5 10-5" />
      </svg>
    </span>
  )
}

function ChildButton({ child, childOptions, onPick }) {
  if (!child) return <span className="font-bold text-ink">{t('Кабинет родителя')}</span>
  return (
    <button
      type="button"
      onClick={() => childOptions.length > 1 && onPick()}
      className={cn(
        'flex min-w-0 max-w-md items-center gap-2 rounded-lg px-1.5 py-1 text-left',
        childOptions.length > 1 && 'hover:bg-canvas',
      )}
      aria-label={childOptions.length > 1 ? t('Выбрать ребёнка') : undefined}
    >
      <Avatar name={child.full_name} src={child.photo_url} />
      <span className="min-w-0">
        <span className="block truncate text-[14px] font-bold text-ink sm:text-[15px]">{child.full_name}</span>
        <span className="block truncate text-[11px] text-ink-muted sm:text-[12px]">{child.organization.name}</span>
      </span>
      {childOptions.length > 1 && <ChevronDown className="size-4 shrink-0 text-ink-muted" />}
    </button>
  )
}

function ParentSidebar({ collapsed }) {
  const { profile, child, signOut } = useParent()
  return (
    <>
      <div className={cn('flex h-16 shrink-0 items-center gap-2.5 border-b border-line', collapsed ? 'justify-center' : 'px-5')}>
        <BrandMark />
        {!collapsed && <span className="text-[17px] font-bold tracking-tight text-ink">KidsCRM</span>}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {!collapsed && <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-subtle">{t('Личный кабинет')}</p>}
        {collapsed && <div className="mx-2 mb-2 h-px bg-line" aria-hidden="true" />}
        <ul className="space-y-0.5">
          {PARENT_NAV.map(item => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
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
      </nav>

      <div className={cn('border-t border-line p-3', collapsed && 'flex flex-col items-center gap-1 px-2')}>
        <div className={cn('flex items-center gap-1', collapsed && 'justify-center')}>
          <NavLink
            to="/parent/profile"
            title={collapsed ? (profile?.full_name || t('Родитель')) : t('Профиль')}
            className={({ isActive }) => cn(
              'flex min-w-0 flex-1 items-center gap-3 rounded-md py-2 transition-colors',
              collapsed ? 'justify-center px-1' : 'px-2',
              isActive ? 'bg-brand-50' : 'hover:bg-surface-muted',
            )}
          >
            <Avatar name={profile?.full_name || t('Родитель')} />
            {!collapsed && (
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-ink">{profile?.full_name || t('Родитель')}</span>
                <span className="block truncate text-xs text-ink-muted">{child?.full_name || t('Личный кабинет')}</span>
              </span>
            )}
          </NavLink>
          {!collapsed && (
            <button type="button" onClick={() => signOut()} className="rounded-md p-2 text-ink-subtle hover:bg-surface-muted hover:text-ink" title={t('Выйти')} aria-label={t('Выйти')}>
              <LogOut className="size-4" />
            </button>
          )}
        </div>
        {collapsed && (
          <button type="button" onClick={() => signOut()} className="rounded-md p-2 text-ink-subtle hover:bg-surface-muted hover:text-ink" title={t('Выйти')} aria-label={t('Выйти')}>
            <LogOut className="size-4" />
          </button>
        )}
      </div>
    </>
  )
}

function ChildPicker({ onClose }) {
  const { children, child, selectChild } = useParent()
  return (
    <Modal open onClose={onClose} title={t('Чей кабинет открыть?')} size="sm">
      <ul className="-mx-2 space-y-1">
        {children.map(candidate => (
          <li key={candidate.id}>
            <button
              type="button"
              onClick={() => { selectChild(candidate.id); onClose() }}
              className={cn('flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left', candidate.id === child?.id ? 'bg-brand-50' : 'hover:bg-canvas')}
            >
              <Avatar name={candidate.full_name} src={candidate.photo_url} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold text-ink">{candidate.full_name}</span>
                <span className="block truncate text-[12.5px] text-ink-muted">
                  {[candidate.organization.name, ...candidate.branches].join(' · ')}{candidate.status === 'left' ? ` · ${t('не ходит')}` : ''}
                </span>
              </span>
              {candidate.id === child?.id && <Check className="size-4 shrink-0 text-brand-600" />}
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  )
}

/** Колокольчик объявлений центра в шапке — со счётчиком непрочитанных. */
function NewsBell() {
  const { data } = usePortalData('announcements/')
  const unread = data?.unread || 0
  return (
    <Link to="/parent/news" aria-label={unread ? t('Объявления, новых: {n}', { n: unread }) : t('Объявления')} className="relative flex size-10 shrink-0 items-center justify-center rounded-lg text-ink-muted hover:bg-canvas">
      <Bell className="size-5" />
      {unread > 0 && <span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-bold text-white">{unread}</span>}
    </Link>
  )
}
