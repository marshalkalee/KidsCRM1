import OrganizationForm from '../components/OrganizationForm'
import AIUsageCard from '../components/ai/AIUsageCard'
import { useSession } from '../session/SessionContext'
import { useNavigate } from 'react-router-dom'
import { KeyRound } from 'lucide-react'
import { Button, PageHeader } from '../ui'
import { t } from '../i18n'

/** Настройки организации (TRU-85) — только владелец. Ниже — расход ИИ-помощника
 * за месяц (TRU-160), если опция подключена. */
export default function OrganizationSettings() {
  const { reload } = useSession()
  const navigate = useNavigate()
  return (
    <div className="space-y-4">
      <PageHeader
        title={t('Организация')}
        description={t('Название, часовой пояс и когда подсвечивать продления, долги и пустые группы.')}
        actions={<Button icon={KeyRound} onClick={() => navigate('/settings/api-keys')}>{t('API-ключи')}</Button>}
      />
      <OrganizationForm wide onSaved={() => reload()} />
      <AIUsageCard />
    </div>
  )
}
