import OrganizationForm from '../components/OrganizationForm'
import { useSession } from '../session/SessionContext'
import { PageHeader } from '../ui'
import { t } from '../i18n'

/** Настройки организации (TRU-85) — только владелец. */
export default function OrganizationSettings() {
  const { reload } = useSession()
  return (
    <div>
      <PageHeader title={t('Организация')} description={t('Название, часовой пояс и когда подсвечивать продления, долги и пустые группы.')} />
      <OrganizationForm onSaved={() => reload()} />
    </div>
  )
}
