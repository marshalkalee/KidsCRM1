import OrganizationForm from '../components/OrganizationForm'
import AIUsageCard from '../components/ai/AIUsageCard'
import { useSession } from '../session/SessionContext'
import { PageHeader } from '../ui'
import { t } from '../i18n'

/** Настройки организации (TRU-85) — только владелец. Ниже — расход ИИ-помощника
 * за месяц (TRU-160), если опция подключена. */
export default function OrganizationSettings() {
  const { reload } = useSession()
  return (
    <div className="space-y-4">
      <PageHeader title={t('Организация')} description={t('Название, часовой пояс и когда подсвечивать продления, долги и пустые группы.')} />
      <OrganizationForm wide onSaved={() => reload()} />
      <AIUsageCard />
    </div>
  )
}
