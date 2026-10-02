import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { Bell, Check, ChevronDown, CloudOff } from 'lucide-react'
import { Avatar, Modal, cn, formatDateTime } from '../ui'
import { t, useLang } from '../i18n'
import { useParent } from './useParent'
import { usePortalData } from './api'
import { installPwa } from './pwa'
import { PARENT_NAV } from './nav'

/*
 * Каркас кабинета (TRU-137): шапка с выбором ребёнка, пометка «нет связи»,
 * экран, нижняя навигация. Сначала телефон: на широком экране то же самое,
 * по центру колонкой. Экраны кабинета — вкладки PARENT_NAV, каждый
 * получает ребёнка из useParent().child (docs/parent-portal.md).
 */

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

export default function ParentLayout() {
  useLang()
  const { child, children, me } = useParent()
  const [picking, setPicking] = useState(false)
  const online = useOnline()

  useEffect(() => { installPwa() }, [])

  return (
    <div className="flex min-h-dvh flex-col bg-canvas pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-8">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
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
        <nav aria-label={t('Разделы кабинета')} className="mx-auto hidden max-w-2xl gap-1 px-4 md:flex">
          {PARENT_NAV.map(item => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => cn('-mb-px border-b-2 px-3 py-2.5 text-sm font-semibold', isActive ? 'border-brand-600 text-brand-700' : 'border-transparent text-ink-muted hover:text-ink')}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      {(!online || me.stale) && (
        <p role="status" className="mx-auto mt-3 flex w-[calc(100%-2rem)] max-w-2xl items-center gap-2 rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-warning-600">
          <CloudOff className="size-4 shrink-0" />
          {me.savedAt
            ? t('Нет связи. Показаны данные от {time} — могут быть неактуальны.', { time: formatDateTime(me.savedAt) })
            : t('Нет связи. Данные могут быть неактуальны.')}
        </p>
      )}

      <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-4">
        <Outlet />
      </main>

      <nav aria-label={t('Разделы кабинета')} className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        <div className="mx-auto grid max-w-2xl grid-cols-5">
          {PARENT_NAV.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => cn('flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-semibold', isActive ? 'text-brand-600' : 'text-ink-muted')}
            >
              <item.icon className="size-5" />
              <span className="max-w-full truncate px-1">{item.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>

      {picking && <ChildPicker onClose={() => setPicking(false)} />}
    </div>
  )
}

function ChildPicker({ onClose }) {
  const { children, child, selectChild } = useParent()
  return (
    <Modal open onClose={onClose} title={t('Чей кабинет открыть?')} size="sm">
      <ul className="-mx-2 space-y-1">
        {children.map(c => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => { selectChild(c.id); onClose() }}
              className={cn('flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left', c.id === child?.id ? 'bg-brand-50' : 'hover:bg-canvas')}
            >
              <Avatar name={c.full_name} src={c.photo_url} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold text-ink">{c.full_name}</span>
                <span className="block truncate text-[12.5px] text-ink-muted">
                  {[c.organization.name, ...c.branches].join(' · ')}{c.status === 'left' ? ` · ${t('не ходит')}` : ''}
                </span>
              </span>
              {c.id === child?.id && <Check className="size-4 shrink-0 text-brand-600" />}
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
