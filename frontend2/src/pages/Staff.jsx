import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Pencil, Plus, UserRoundCog } from 'lucide-react'
import api from '../api/axios'
import StaffModal from '../components/StaffModal'
import { ROLE_LABELS } from '../session/SessionContext'
import { Avatar, Badge, Button, DataTable, EmptyState, PageHeader, plural } from '../ui'
import { t } from '../i18n'

export default function Staff() {
  const navigate = useNavigate()
  const [staff, setStaff] = useState(null)
  const [branches, setBranches] = useState([])
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = useCallback(() => {
    Promise.all([api.get('users/'), api.get('branches/')])
      .then(([users, branchList]) => {
        setStaff(users.data.results || users.data)
        setBranches(branchList.data.results || branchList.data)
        setError(false)
      })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  const branchNames = useMemo(() => Object.fromEntries(branches.map(branch => [String(branch.id), branch.name])), [branches])
  const activeCount = staff?.filter(person => person.is_active).length || 0
  const rows = [...(staff || []).filter(person => person.is_active), ...(staff || []).filter(person => !person.is_active)]
  const columns = [
    {
      key: 'full_name', header: t('Сотрудник'), primary: true,
      render: person => <span className="flex items-center gap-3"><Avatar name={person.full_name} src={person.photo_url} /><span className="font-semibold text-ink">{person.full_name}</span></span>,
    },
    { key: 'role', header: t('Роль'), render: person => <Badge tone={person.role === 'teacher' ? 'brand' : 'neutral'}>{ROLE_LABELS[person.role] || person.role}</Badge> },
    { key: 'phone', header: t('Телефон'), className: 'text-ink-muted whitespace-nowrap' },
    {
      key: 'branches', header: t('Филиалы'), hideOnMobile: true,
      render: person => person.branches?.length ? person.branches.map(id => branchNames[String(id)]).filter(Boolean).join(', ') : t('Все филиалы'),
    },
    { key: 'status', header: t('Статус'), mobileAside: true, render: person => <Badge tone={person.is_active ? 'success' : 'neutral'}>{person.is_active ? t('Активен') : t('Отключён')}</Badge> },
    {
      key: 'actions', header: '', align: 'right',
      render: person => <Button variant="ghost" size="icon" aria-label={t('Изменить')} onClick={event => { event.stopPropagation(); setEditing(person) }}><Pencil className="size-4" /></Button>,
    },
  ]

  return (
    <div>
      <PageHeader
        title={t('Сотрудники')}
        description={staff ? `${activeCount} ${plural(activeCount, ['активный сотрудник', 'активных сотрудника', 'активных сотрудников'])}` : t('Загрузка…')}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новый сотрудник')}</Button>}
      />
      <DataTable
        columns={columns}
        rows={rows}
        loading={!staff && !error}
        error={error}
        onRetry={load}
        onRowClick={person => navigate(`/staff/${person.id}`, { state: { from: '/staff', label: t('Сотрудники') } })}
        empty={<EmptyState icon={UserRoundCog} title={t('Сотрудников пока нет')} description={t('Добавьте сотрудников и назначьте им роли.')} action={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новый сотрудник')}</Button>} />}
      />
      {editing && <StaffModal staff={editing === 'new' ? null : editing} branches={branches} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
    </div>
  )
}
