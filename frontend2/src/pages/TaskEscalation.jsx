import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, UserCheck } from 'lucide-react'
import api from '../api/axios'
import { useSession } from '../session/SessionContext'
import { Avatar, Badge, Button, Card, CardHeader, EmptyState, ErrorState, Modal, PageHeader, Select, Skeleton, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'

const TYPE_LABELS = {
  call_back: 'Перезвонить',
  payment_reminder: 'Напомнить об оплате',
  trial_signup: 'Записать на пробное',
  renewal_offer: 'Предложить продление',
  missing_subscription: 'Нет абонемента',
  trial_no_show: 'Не пришёл на пробное',
  other: 'Другое',
}

export default function TaskEscalation() {
  const { branches } = useSession()
  const toast = useToast()
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [branchFilter, setBranchFilter] = useState('')
  const [colleagues, setColleagues] = useState([])
  const [reassigning, setReassigning] = useState(null)

  const load = useCallback(() => {
    api.get('tasks/escalation/', { params: branchFilter ? { branch: branchFilter } : {} })
      .then(res => { setData(res.data); setError(false) })
      .catch(() => setError(true))
  }, [branchFilter])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    api.get('users/').then(res => {
      setColleagues((res.data.results || res.data).filter(u => u.role !== 'teacher'))
    }).catch(() => {})
  }, [])

  async function reassignOpen(assigneeId, newAssigneeId) {
    try {
      const response = await api.get('tasks/', { params: { assigned_to: assigneeId, status: 'open' } })
      const rows = response.data.results || response.data
      await Promise.all(rows.map(task => api.patch(`tasks/${task.id}/`, { assigned_to: newAssigneeId })))
      toast.success(t('Задачи переданы'))
      setReassigning(null)
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (data === null) return <Skeleton className="h-96" />

  return (
    <div>
      <PageHeader
        title={t('Эскалация просроченных задач')}
        description={t('{n} просроченных задач по вашим филиалам', { n: data.total_overdue })}
        actions={branches.length > 1 && (
          <Select value={branchFilter} onChange={e => setBranchFilter(e.target.value)}>
            <option value="">{t('Все филиалы')}</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </Select>
        )}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card padded={false} className="overflow-hidden">
          <div className="px-5 pt-5"><CardHeader title={t('По сотрудникам')} description={t('У кого сколько просрочено — можно передать всё коллеге')} /></div>
          {data.by_employee.length === 0 ? (
            <EmptyState title={t('Просрочек нет')} className="py-8" />
          ) : (
            <ul className="divide-y divide-line border-t border-line">
              {data.by_employee.map(row => (
                <li key={row.assigned_to || 'unassigned'} className="flex items-center gap-3 px-5 py-3">
                  <Avatar name={row.name} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold text-ink">{row.name}</p>
                    <p className="text-[13px] text-ink-muted">
                      {t('Открыто: {open}, просрочено: {overdue}', { open: row.open, overdue: row.overdue })}
                      {row.oldest_due_at && ` · ${t('самая старая с {date}', { date: new Date(row.oldest_due_at).toLocaleDateString('ru-RU') })}`}
                    </p>
                  </div>
                  <Badge tone="danger">{row.overdue}</Badge>
                  {row.assigned_to && (
                    <Button size="sm" variant="secondary" icon={UserCheck} onClick={() => setReassigning(row)} aria-label={t('Передать всё')} title={t('Передать всё')}>
                      <span className="hidden sm:inline">{t('Передать всё')}</span>
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card padded={false} className="self-start overflow-hidden">
          <div className="px-5 pt-5"><CardHeader title={t('По типу задачи')} description={t('Что чаще всего не успевают')} /></div>
          {data.by_type.length === 0 ? (
            <EmptyState title={t('Просрочек нет')} className="py-8" />
          ) : (
            <ul className="divide-y divide-line border-t border-line">
              {data.by_type.map(row => (
                <li key={row.type} className="flex items-center justify-between gap-3 px-5 py-2.5">
                  <span className="flex min-w-0 items-center gap-2 text-ink">
                    <AlertTriangle className="size-4 shrink-0 text-danger-600" />
                    <span className="truncate">{t(row.label || TYPE_LABELS[row.type] || row.type)}</span>
                  </span>
                  <Badge tone="danger">{row.count}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {reassigning && (
        <Modal open onClose={() => setReassigning(null)} title={t('Передать все открытые задачи {name}', { name: reassigning.name })}>
          <Select defaultValue="" onChange={e => e.target.value && reassignOpen(reassigning.assigned_to, e.target.value)}>
            <option value="" disabled>{t('Выберите сотрудника')}</option>
            {colleagues.filter(c => String(c.id) !== reassigning.assigned_to).map(c => (
              <option key={c.id} value={c.id}>{c.full_name}</option>
            ))}
          </Select>
        </Modal>
      )}
    </div>
  )
}