import { useNavigate } from 'react-router-dom'
import { ArrowRight, CheckCheck, ChevronRight, CircleCheck } from 'lucide-react'
import { useNotifications } from '../components/notifications/NotificationList'
import { NOTIFICATION_KINDS } from '../components/notifications/kinds'
import { Button, Card, PageHeader, Skeleton, cn } from '../ui'
import { t } from '../i18n'

/**
 * Центр уведомлений (TRU-72): всё, что требует внимания, — плитками на всю
 * ширину, новое выделено. Где всё в порядке — одной строкой внизу.
 */
export default function Notifications() {
  const navigate = useNavigate()
  const { data, markSeen } = useNotifications()
  const items = data?.items || []
  const active = items.filter(item => item.available && item.count > 0 && NOTIFICATION_KINDS[item.kind])
  const quiet = items.filter(item => !(item.available && item.count > 0) && NOTIFICATION_KINDS[item.kind])

  function open(item) {
    markSeen(item.kind)
    navigate(item.link)
  }

  return (
    <div>
      <PageHeader
        title={t('Уведомления')}
        description={data ? (data.unread ? t('Новое: {n}', { n: data.unread }) : t('Нового нет')) : t('Загрузка…')}
        actions={data?.unread > 0 && <Button icon={CheckCheck} onClick={() => markSeen('all')}>{t('Прочитать все')}</Button>}
      />

      {!data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map(i => <Skeleton key={i} className="h-40" />)}
        </div>
      ) : active.length === 0 ? (
        <Card className="flex flex-col items-center py-12 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-success-50 text-success-600"><CircleCheck className="size-6" /></span>
          <p className="mt-3 text-base font-bold text-ink">{t('Всё в порядке')}</p>
          <p className="mt-1 text-sm text-ink-muted">{t('Нет того, что требует внимания прямо сейчас.')}</p>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 sm:gap-4 xl:grid-cols-3">
          {active.map(item => {
            const meta = NOTIFICATION_KINDS[item.kind]
            const Icon = meta.icon
            return (
              <button
                key={item.kind}
                type="button"
                onClick={() => open(item)}
                className={cn(
                  'group rounded-xl border bg-surface text-left shadow-card transition hover:border-brand-300 hover:shadow-pop',
                  item.unread ? 'border-brand-200' : 'border-line',
                )}
              >
                {/* Телефон — строка, шире — плитка. */}
                <div className="flex items-center gap-3 p-4 sm:hidden">
                  <span className={cn('relative flex size-10 shrink-0 items-center justify-center rounded-xl', meta.tone)}>
                    <Icon className="size-5" />
                    {item.unread && <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full bg-brand-600 ring-2 ring-surface" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cn('block text-sm text-ink', item.unread ? 'font-bold' : 'font-semibold')}>{meta.title}</span>
                    <span className="block text-[12.5px] text-ink-muted">{meta.text(item)}</span>
                  </span>
                  <span className="text-lg font-bold tabular-nums text-ink">{item.count}</span>
                  <ChevronRight className="size-4 shrink-0 text-ink-subtle" />
                </div>
                <div className="hidden h-full flex-col p-5 sm:flex">
                <div className="flex items-start justify-between gap-3">
                  <span className={cn('flex size-11 items-center justify-center rounded-xl', meta.tone)}>
                    <Icon className="size-5" />
                  </span>
                  {item.unread && <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-brand-600">{t('Новое')}</span>}
                </div>
                <p className="mt-4 text-3xl font-bold tabular-nums text-ink">{item.count}</p>
                <p className={cn('mt-1 text-[15px] text-ink', item.unread ? 'font-bold' : 'font-semibold')}>{meta.title}</p>
                <p className="mt-0.5 flex-1 text-[13px] text-ink-muted">{meta.text(item)}</p>
                <span className="mt-4 inline-flex items-center gap-1 text-[13px] font-semibold text-brand-600">
                  {t('Открыть')}<ArrowRight className="size-4 transition group-hover:translate-x-0.5" />
                </span>
                </div>
              </button>
            )
          })}
        </div>
      )}

      {data && quiet.length > 0 && (
        <div className="mt-6">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-subtle">{t('Всё в порядке')}</p>
          <div className="flex flex-wrap gap-2">
            {quiet.map(item => {
              const meta = NOTIFICATION_KINDS[item.kind]
              const Icon = meta.icon
              return (
                <span key={item.kind} className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-muted">
                  <Icon className="size-4 text-ink-subtle" />{meta.title}
                  {!item.available && <span className="text-ink-subtle">· {t('скоро')}</span>}
                </span>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
