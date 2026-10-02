import { Card, EmptyState } from '../../ui'
import { t } from '../../i18n'

/** Экран кабинета, который ещё делается (TRU-138, 139, 142, 145): вкладка уже есть, содержимое — скоро. */
export default function ParentSoon({ icon, title }) {
  return (
    <Card>
      <EmptyState icon={icon} title={title} description={t('Этот раздел скоро появится.')} />
    </Card>
  )
}
