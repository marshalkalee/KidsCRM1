import OrganizationForm from '../components/OrganizationForm'
import { useSession } from '../session/SessionContext'
import { PageHeader } from '../ui'

/** Настройки организации (TRU-85) — только владелец. */
export default function OrganizationSettings() {
  const { reload } = useSession()
  return (
    <div>
      <PageHeader title="Организация" description="Название, часовой пояс и когда подсвечивать продления, долги и пустые группы." />
      <OrganizationForm onSaved={() => reload()} />
    </div>
  )
}
