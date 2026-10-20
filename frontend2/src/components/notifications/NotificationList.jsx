import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import api from '../../api/axios'
import { cn } from '../../ui'
import { t } from '../../i18n'
import { NOTIFICATION_KINDS } from './kinds'

export const NOTIFICATIONS_EVENT = 'kc:notifications-changed'
const POLL_MS = 10_000

/** Уведомления с сервера; обновляются раз в минуту и по событию. */
export function useNotifications() {
  const [data, setData] = useState(null)
  const load = useCallback(() => {
    api.get('notifications/').then(res => setData(res.data)).catch(() => {})
  }, [])
  useEffect(() => {
    load()
    const refreshVisible = () => {
      if (document.visibilityState === 'visible') load()
    }
    const timer = setInterval(refreshVisible, POLL_MS)
    const onEvent = () => load()
    window.addEventListener(NOTIFICATIONS_EVENT, onEvent)
    window.addEventListener('kc:branch-changed', onEvent)
    window.addEventListener('kc:lead-created', onEvent)
    window.addEventListener('focus', refreshVisible)
    document.addEventListener('visibilitychange', refreshVisible)
    return () => {
      clearInterval(timer)
      window.removeEventListener(NOTIFICATIONS_EVENT, onEvent)
      window.removeEventListener('kc:branch-changed', onEvent)
      window.removeEventListener('kc:lead-created', onEvent)
      window.removeEventListener('focus', refreshVisible)
      document.removeEventListener('visibilitychange', refreshVisible)
    }
  }, [load])

  const markSeen = useCallback(async kind => {
    try {
      const res = await api.post('notifications/seen/', { kind })
      setData(res.data)
      window.dispatchEvent(new CustomEvent(NOTIFICATIONS_EVENT))
    } catch { /* не критично: отметка просто не сохранится */ }
  }, [])

  return { data, markSeen, reload: load }
}

/**
 * Список уведомлений: сначала то, где что-то есть; пустые — «всё в
 * порядке» внизу, приглушённо (обработанное скрывается из внимания).
 * Клик — отметить прочитанным и перейти прямо в нужный экран.
 */
export function NotificationList({ items, onMarkSeen, onNavigate, compact = false }) {
  const navigate = useNavigate()
  const active = items.filter(item => item.available && item.count > 0)
  const quiet = items.filter(item => !item.available || item.count === 0)

  function open(item) {
    onMarkSeen(item.kind)
    onNavigate?.()
    navigate(item.link)
  }

  return (
    <div>
      {active.length === 0 && (
        <div className="px-4 py-6 text-center">
          <p className="text-sm font-semibold text-ink">{t('Всё в порядке')}</p>
          <p className="mt-1 text-[13px] text-ink-muted">{t('Нет того, что требует внимания прямо сейчас.')}</p>
        </div>
      )}
      <ul className="divide-y divide-line">
        {active.map(item => {
          const meta = NOTIFICATION_KINDS[item.kind]
          if (!meta) return null
          const Icon = meta.icon
          return (
            <li key={item.kind}>
              <button type="button" onClick={() => open(item)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-surface-muted">
                <span className={cn('relative flex size-9 shrink-0 items-center justify-center rounded-full', meta.tone)}>
                  <Icon className="size-[18px]" />
                  {item.unread && <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full bg-brand-600 ring-2 ring-surface" aria-label={t('Новое')} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cn('block text-sm text-ink', item.unread ? 'font-bold' : 'font-semibold')}>{meta.title}</span>
                  <span className="block text-[13px] text-ink-muted">{meta.text(item)}</span>
                </span>
                <span className="rounded-full bg-surface-muted px-2 py-0.5 text-xs font-bold text-ink">{item.count}</span>
                <ChevronRight className="size-4 shrink-0 text-ink-subtle" />
              </button>
            </li>
          )
        })}
      </ul>
      {!compact && quiet.length > 0 && (
        <ul className="mt-2 border-t border-line pt-2">
          {quiet.map(item => {
            const meta = NOTIFICATION_KINDS[item.kind]
            if (!meta) return null
            const Icon = meta.icon
            return (
              <li key={item.kind} className="flex items-center gap-3 px-4 py-2 text-[13px] text-ink-subtle">
                <Icon className="size-4" />
                <span className="flex-1">{meta.title}</span>
                <span>{item.available ? t('всё в порядке') : t('скоро')}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
