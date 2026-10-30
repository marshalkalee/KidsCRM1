import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  AlarmClock,
  Bell,
  CalendarX,
  Check,
  ChevronDown,
  CloudOff,
  LogOut,
  Megaphone,
  Menu,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  UserRound,
  Wallet,
} from 'lucide-react'
import { Avatar, ErrorBoundary, Modal, cn, formatDate, formatDateTime } from '../ui'
import { t, useLang } from '../i18n'
import logoMark from '../assets/logo-mark.png'
import { useParent } from './useParent'
import portal, { usePortalData } from './api'
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
 * рабочая область. На телефоне — то же меню, выезжающее слева по кнопке
 * в шапке (кабинет открывают как сайт, а не как приложение).
 * Сессия остаётся родительской: служебные API и разделы недоступны даже по URL.
 */
export default function ParentLayout() {
  useLang()
  const { child, children, me } = useParent()
  const [picking, setPicking] = useState(false)
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [drawer, setDrawer] = useState(false)
  const location = useLocation()
  // Перешли в раздел — меню на телефоне закрывается.
  const [path, setPath] = useState(location.pathname)
  if (path !== location.pathname) {
    setPath(location.pathname)
    setDrawer(false)
  }
  const online = useOnline()
  const { data: noteData, reload: reloadNotes } = usePortalData(
    child && `children/${child.id}/notes/`,
    { refreshInterval: 10_000, refreshOnFocus: true },
  )
  const noteUnread = noteData?.unread || 0

  useEffect(() => {
    const refreshNotes = () => reloadNotes()
    window.addEventListener('kc-parent-notes-read', refreshNotes)
    return () => window.removeEventListener('kc-parent-notes-read', refreshNotes)
  }, [reloadNotes])

  useEffect(() => { installPwa() }, [])

  function toggleCollapsed() {
    setCollapsed(value => {
      try { localStorage.setItem(COLLAPSED_KEY, value ? '0' : '1') } catch { /* приватный режим */ }
      return !value
    })
  }

  return (
    <div className={cn(
      'min-h-dvh bg-canvas transition-[padding] duration-200',
      collapsed ? 'lg:pl-[76px]' : 'lg:pl-64',
    )}>
      <aside className={cn(
        'fixed inset-y-0 left-0 z-30 hidden border-r border-line bg-surface transition-[width] duration-200 lg:flex lg:flex-col',
        collapsed ? 'w-[76px]' : 'w-64',
      )}>
        <ParentSidebar collapsed={collapsed} noteUnread={noteUnread} />
      </aside>

      {/* Телефон: меню слева поверх страницы. */}
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label={t('Меню')}>
          <button type="button" className="absolute inset-0 bg-ink/40" onClick={() => setDrawer(false)} aria-label={t('Закрыть меню')} />
          <aside className="relative flex h-full w-72 max-w-[85vw] flex-col bg-surface shadow-pop">
            <ParentSidebar collapsed={false} noteUnread={noteUnread} />
          </aside>
        </div>
      )}

      {/* Шапка закреплена через fixed, а не sticky: Safari на iPhone красит
          полосу у строки состояния в цвет fixed-элемента у верхнего края; со
          sticky там просвечивала прокрученная страница. */}
      <header className={cn('fixed inset-x-0 top-0 z-20 border-b border-line bg-surface transition-[left] duration-200', collapsed ? 'lg:left-[76px]' : 'lg:left-64')}>
        <div className="mx-auto flex h-16 max-w-[1500px] items-center gap-3 px-4 sm:px-6 lg:max-w-none">
          <button
            type="button"
            onClick={() => setDrawer(true)}
            className="-ml-1.5 relative rounded-md p-2 text-ink-muted hover:bg-surface-muted hover:text-ink lg:hidden"
            aria-label={t('Меню')}
          >
            <Menu className="size-6" />
            {noteUnread > 0 && <span className="absolute right-1 top-1 size-2 rounded-full bg-brand-600 ring-2 ring-surface" />}
          </button>
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
          <div className="ml-auto">
            <NotificationsBell noteUnread={noteUnread} />
          </div>
        </div>
      </header>
      <div className="h-16" aria-hidden="true" />

      <main className="mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
        {(!online || me.stale) && (
          <p role="status" className="mb-4 flex items-center gap-2 rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-warning-600">
            <CloudOff className="size-4 shrink-0" />
            {me.savedAt
              ? t('Нет связи. Показаны данные от {time} — могут быть неактуальны.', { time: formatDateTime(me.savedAt) })
              : t('Нет связи. Данные могут быть неактуальны.')}
          </p>
        )}
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>


      {picking && <ChildPicker onClose={() => setPicking(false)} />}
    </div>
  )
}

function BrandMark({ className }) {
  return (
    <img src={logoMark} alt="" aria-hidden="true" className={cn('h-7 w-auto shrink-0 select-none', className)} draggable={false} />
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

function ParentSidebar({ collapsed, noteUnread }) {
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
                {item.to === '/parent/notes' && noteUnread > 0 && (
                  <span className={cn('flex min-w-5 items-center justify-center rounded-full bg-brand-600 px-1.5 text-[10px] font-bold text-white', !collapsed && 'ml-auto')}>{noteUnread}</span>
                )}
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
            // Карточка — ссылка на профиль, а не пункт меню: подсветка только по наведению.
            className={cn(
              'flex min-w-0 flex-1 items-center gap-3 rounded-md py-2 transition-colors hover:bg-surface-muted',
              collapsed ? 'justify-center px-1' : 'px-2',
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

const BELL_LIMIT = 8

// Иконка служебного уведомления — по событию центра рассылок.
const SERVICE_ICONS = {
  subscription_ending: { icon: Wallet, tone: 'bg-warning-50 text-warning-600' },
  payment_due: { icon: Wallet, tone: 'bg-danger-50 text-danger-600' },
  lesson_cancelled: { icon: CalendarX, tone: 'bg-danger-50 text-danger-600' },
  lesson_reminder: { icon: AlarmClock, tone: 'bg-brand-50 text-brand-600' },
  teacher_substitute: { icon: UserRound, tone: 'bg-brand-50 text-brand-600' },
}
const NEWS_ICON = { icon: Megaphone, tone: 'bg-info-50 text-info-600' }

/**
 * Колокольчик в шапке — как у сотрудников: окно поверх страницы, а не
 * переход. Внутри — новые заметки преподавателя, напоминания центра
 * (абонемент, оплата, отмена — даже если push не дошёл) и объявления.
 * Нажали — прочитано и открыт нужный раздел.
 */
function NotificationsBell({ noteUnread }) {
  const navigate = useNavigate()
  const live = { refreshInterval: 60_000, refreshOnFocus: true }
  const { data, reload } = usePortalData('announcements/', live)
  const { data: feed, reload: reloadFeed } = usePortalData('notifications/feed/', live)
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const rows = data && feed
    ? [
      ...feed.results.map(row => ({
        key: `s:${row.id}`, id: row.id, service: true, title: row.title, text: row.text,
        date: row.created_at, read: row.read, link: row.link, look: SERVICE_ICONS[row.event] || NEWS_ICON,
      })),
      ...data.results.map(row => ({
        key: `a:${row.id}`, id: row.id, service: false, title: row.title, text: row.body,
        date: row.published_at, read: row.read, link: '/parent/announcements', look: NEWS_ICON,
      })),
    ].sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, BELL_LIMIT)
    : null
  const unreadNews = (data?.unread || 0) + (feed?.unread || 0)
  const unread = unreadNews + noteUnread

  useEffect(() => {
    if (!open) return undefined
    const onDown = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  async function markRead(items) {
    const news = items.filter(item => !item.service).map(item => item.id)
    const service = items.filter(item => item.service).map(item => item.id)
    await Promise.all([
      ...news.map(id => portal.post(`announcements/${id}/read/`).catch(() => {})),
      service.length ? portal.post('notifications/feed/read/', { ids: service }).catch(() => {}) : null,
    ])
    reload()
    reloadFeed()
  }

  async function markAllRead() {
    await Promise.all([
      ...(data?.results || []).filter(row => !row.read).map(row => portal.post(`announcements/${row.id}/read/`).catch(() => {})),
      portal.post('notifications/feed/read/', {}).catch(() => {}),
    ])
    reload()
    reloadFeed()
  }

  function openItem(item) {
    if (!item.read) markRead([item])
    setOpen(false)
    navigate(item.link)
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-label={unread ? t('Уведомления: новых {n}', { n: unread }) : t('Уведомления')}
        className={cn('relative flex size-10 shrink-0 items-center justify-center rounded-lg hover:bg-canvas', unread ? 'text-brand-600' : 'text-ink-muted')}
      >
        <Bell className="size-5" />
        {unread > 0 && <span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-bold text-white">{unread}</span>}
      </button>
      {open && (
        <div className="fixed inset-x-3 top-16 z-40 overflow-hidden rounded-lg border border-line bg-surface shadow-pop sm:absolute sm:inset-x-auto sm:right-0 sm:top-12 sm:w-96">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <p className="text-sm font-bold text-ink">{t('Уведомления')}</p>
            {unreadNews > 0 && (
              <button type="button" onClick={markAllRead} className="text-[13px] font-semibold text-brand-600 hover:underline">
                {t('Прочитать все')}
              </button>
            )}
          </div>
          <div className="max-h-[60vh] overflow-y-auto">
            {noteUnread > 0 && (
              <Link to="/parent/notes" onClick={() => setOpen(false)} className="flex items-center gap-3 border-b border-line bg-brand-50/50 px-4 py-3 hover:bg-brand-50">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600"><NotebookPen className="size-4" /></span>
                <span className="min-w-0 flex-1 text-sm font-semibold text-ink">{t('Новые заметки преподавателя: {n}', { n: noteUnread })}</span>
                <span className="size-2 shrink-0 rounded-full bg-brand-600" />
              </Link>
            )}
            {!rows ? (
              <p className="px-4 py-6 text-center text-sm text-ink-muted">{t('Загрузка…')}</p>
            ) : rows.length === 0 && !noteUnread ? (
              <div className="px-4 py-8 text-center">
                <Bell className="mx-auto size-6 text-ink-subtle" />
                <p className="mt-2 text-sm font-semibold text-ink">{t('Новых уведомлений нет')}</p>
                <p className="mt-0.5 text-[13px] text-ink-muted">{t('Здесь появятся напоминания центра, объявления и заметки преподавателя.')}</p>
              </div>
            ) : (
              <ul className="divide-y divide-line">
                {rows.map(item => {
                  const Icon = item.look.icon
                  return (
                    <li key={item.key}>
                      <button type="button" onClick={() => openItem(item)} className={cn('flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-surface-muted', !item.read && 'bg-brand-50/30')}>
                        <span className={cn('mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full', item.look.tone)}><Icon className="size-4" /></span>
                        <span className="min-w-0 flex-1">
                          <span className={cn('block truncate text-sm text-ink', !item.read ? 'font-bold' : 'font-semibold')}>{item.title}</span>
                          <span className="mt-0.5 line-clamp-2 text-[13px] text-ink-muted">{item.text}</span>
                          <span className="mt-1 block text-[12px] text-ink-subtle">{item.service ? formatDateTime(item.date) : formatDate(item.date)}</span>
                        </span>
                        {!item.read && <span className="mt-2 size-2 shrink-0 rounded-full bg-brand-600" />}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
          <Link to="/parent/announcements" onClick={() => setOpen(false)} className="block border-t border-line px-4 py-2.5 text-center text-[13px] font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink">
            {t('Все объявления')}
          </Link>
        </div>
      )}
    </div>
  )
}
