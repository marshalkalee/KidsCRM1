import { Compass } from 'lucide-react'
import { Button, EmptyState } from '../ui'
import { t } from '../i18n'

export default function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title={t('Страница не найдена')}
      description={t('Возможно, ссылка устарела или раздел ещё переезжает в новый интерфейс.')}
      action={<Button variant="primary" to="/dashboard">{t('На главную')}</Button>}
    />
  )
}
