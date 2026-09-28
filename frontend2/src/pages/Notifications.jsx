import { CheckCheck } from 'lucide-react'
import { NotificationList, useNotifications } from '../components/notifications/NotificationList'
import { Button, Card, PageHeader, Skeleton } from '../ui'
import { t } from '../i18n'

/** Центр уведомлений (TRU-72): всё, что требует внимания, по видам. */
export default function Notifications() {
  const { data, markSeen } = useNotifications()
  return (
    <div>
      <PageHeader
        title={t('Уведомления')}
        description={data ? (data.unread ? t('Новое: {n}', { n: data.unread }) : t('Нового нет')) : t('Загрузка…')}
        actions={data?.unread > 0 && <Button icon={CheckCheck} onClick={() => markSeen('all')}>{t('Прочитать все')}</Button>}
      />
      <Card padded={false} className="max-w-2xl overflow-hidden">
        {data ? <NotificationList items={data.items} onMarkSeen={markSeen} /> : <div className="space-y-3 p-5"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>}
      </Card>
    </div>
  )
}
