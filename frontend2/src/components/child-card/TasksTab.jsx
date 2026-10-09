import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, CheckCircle2, ListTodo, Plus, XCircle } from 'lucide-react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, Select, Skeleton, Textarea,
  apiErrorMessage, cn, formatDate, formatDateTime, useToast,
} from '../../ui'
import { t } from '../../i18n'
import { MANUAL_TYPES } from '../tasks/types'

function todayLocalIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function isOverdue(task) {
  return Boolean(task.due_at) && new Date(task.due_at) < new Date()
}

function initialBranch(branches, activeBranchId) {
  if (branches.length === 0) return activeBranchId ? String(activeBranchId) : ''
  if (branches.length === 1) return branches[0].id
  return (branches.find(b => b.id === String(activeBranchId)) || branches[0]).id
}

/**
 * Вкладка «Задачи» карточки ребёнка (ТЗ п. 4.1, TRU-112): что обещали
 * семье, что сделали и что висит. Показывает задачи и по самому ребёнку,
 * и по его заявкам — до конвертации работа велась по заявке.
 */
export default function TasksTab({ child, card, permissions, onCountChange }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [creating, setCreating] = useState(false)

  const load = useCallback(() => {
    api.get('tasks/for-child/', { params: { child: child.id } })
      .then(res => {
        setData(res.data)
        setError(false)
        onCountChange?.(res.data.open.length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])
  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (data === null) return <Skeleton className="h-40" />

  const { open, closed, closed_total: closedTotal } = data

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-ink">{t('Открытые задачи')}</p>
        {permissions?.can_edit && (
          <Button variant="primary" size="sm" icon={Plus} onClick={() => setCreating(true)}>
            {t('Создать задачу')}
          </Button>
        )}
      </div>

      {open.length === 0 ? (
        <Card>
          <EmptyState icon={ListTodo} title={t('Открытых задач нет')} description={t('Всё, что обещали семье, выполнено.')} />
        </Card>
      ) : (
        <div className="space-y-2">
          {open.map(task => <OpenTaskCard key={task.id} task={task} childId={child.id} />)}
        </div>
      )}

      <p className="pt-2 font-semibold text-ink">{t('История')}</p>
      {closed.length === 0 ? (
        <p className="text-sm text-ink-muted">{t('Закрытых задач пока нет.')}</p>
      ) : (
        <div className="space-y-2">
          {closed.map(task => <ClosedTaskCard key={task.id} task={task} childId={child.id} />)}
          {closedTotal > closed.length && (
            <p className="text-[13px] text-ink-muted">
              {t('Показаны последние {n} из {total}', { n: closed.length, total: closedTotal })}
            </p>
          )}
        </div>
      )}

      {creating && (
        <CreateTaskModal
          child={child}
          card={card}
          onClose={() => setCreating(false)}
          onCreated={() => { setCreating(false); load() }}
        />
      )}
    </div>
  )
}

function OpenTaskCard({ task, childId }) {
  const { can } = useSession()
  const overdue = isOverdue(task)
  const viaLead = task.child !== childId
  return (
    <Card className={overdue ? 'border-danger-600' : undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={overdue ? 'danger' : 'neutral'}>{task.type_display}</Badge>
        {viaLead && <Badge tone="info">{t('По заявке')}</Badge>}
        {task.due_at && (
          <span className={cn('inline-flex items-center gap-1 text-[13px]', overdue ? 'font-semibold text-danger-600' : 'text-ink-muted')}>
            <CalendarClock className="size-3.5" />
            {formatDate(task.due_at)}
          </span>
        )}
      </div>
      <p className="mt-1 font-semibold text-ink">{task.title}</p>
      {task.description && <p className="mt-0.5 whitespace-pre-line text-sm text-ink-muted">{task.description}</p>}
      <p className="mt-1 text-xs text-ink-subtle">
        {t('Исполнитель: {name}', { name: task.assigned_to_name || t('не назначен') })}
        {task.source === 'auto' && ` · ${t('создана автоматически')}`}
      </p>
      {viaLead && task.lead && can('can_manage_leads') && (
        <Link to={`/leads/${task.lead}`} className="mt-1 inline-block text-[13px] text-brand-600 hover:underline">
          {t('Открыть заявку')}
        </Link>
      )}
    </Card>
  )
}

function ClosedTaskCard({ task, childId }) {
  const done = task.status === 'done'
  const viaLead = task.child !== childId
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        {done
          ? <CheckCircle2 className="size-4 text-success-600" />
          : <XCircle className="size-4 text-ink-subtle" />}
        <Badge tone={done ? 'success' : 'neutral'}>{task.status_display}</Badge>
        <Badge tone="neutral">{task.type_display}</Badge>
        {viaLead && <Badge tone="info">{t('По заявке')}</Badge>}
        <span className="text-[13px] text-ink-muted">{formatDateTime(task.updated_at)}</span>
      </div>
      <p className="mt-1 font-semibold text-ink">{task.title}</p>
      {task.closing_comment && (
        <p className="mt-1 rounded-md bg-surface-muted px-3 py-2 text-sm text-ink">{task.closing_comment}</p>
      )}
      <p className="mt-1 text-xs text-ink-subtle">
        {t('Исполнитель: {name}', { name: task.assigned_to_name || t('не назначен') })}
      </p>
    </Card>
  )
}

function CreateTaskModal({ child, card, onClose, onCreated }) {
  const { user, activeBranchId } = useSession()
  const toast = useToast()
  const branches = card?.branches || []
  const [staff, setStaff] = useState([])
  const [form, setForm] = useState(() => ({
    type: 'call_back',
    title: `${MANUAL_TYPES[0].label}: ${child.full_name}`,
    description: '',
    assigned_to: user.id,
    due_date: todayLocalIso(),
    branch: initialBranch(branches, activeBranchId),
  }))
  const [titleTouched, setTitleTouched] = useState(false)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('users/')
      .then(res => setStaff((res.data.results || res.data).filter(u => ['owner', 'manager', 'admin'].includes(u.role) && u.is_active !== false)))
      .catch(() => {})
  }, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  function changeType(value) {
    const label = MANUAL_TYPES.find(x => x.value === value)?.label
    setForm(f => ({ ...f, type: value, title: titleTouched ? f.title : `${label}: ${child.full_name}` }))
  }

  async function submit(e) {
    e.preventDefault()
    if (saving) return
    setSaving(true)
    setErrors({})
    try {
      await api.post('tasks/', {
        type: form.type,
        title: form.title.trim(),
        description: form.description.trim(),
        child: child.id,
        branch: form.branch || null,
        assigned_to: form.assigned_to || null,
        due_at: form.due_date ? new Date(`${form.due_date}T23:59:00`).toISOString() : null,
      })
      toast.success(t('Задача создана'))
      onCreated()
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const assignees = staff.length > 0 ? staff : [{ id: user.id, full_name: user.full_name }]

  return (
    <Modal
      open
      onClose={onClose}
      title={t('Новая задача')}
      description={child.full_name}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="child-task-form" loading={saving}>{t('Создать')}</Button>
        </>
      }
    >
      <form id="child-task-form" onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t('Тип задачи')} required error={errors.type}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} autoFocus value={form.type} onChange={e => changeType(e.target.value)}>
              {MANUAL_TYPES.map(x => <option key={x.value} value={x.value}>{x.label}</option>)}
            </Select>
          )}
        </Field>
        <Field label={t('Что нужно сделать')} required error={errors.title}>
          {({ id, invalid }) => (
            <Input
              id={id}
              invalid={invalid}
              maxLength={255}
              required
              value={form.title}
              onChange={e => { setTitleTouched(true); set('title', e.target.value) }}
            />
          )}
        </Field>
        <Field label={t('Комментарий')} error={errors.description}>
          {({ id }) => (
            <Textarea id={id} rows={2} maxLength={2000} value={form.description} onChange={e => set('description', e.target.value)} />
          )}
        </Field>
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Field label={t('Исполнитель')} error={errors.assigned_to}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.assigned_to} onChange={e => set('assigned_to', e.target.value)}>
                {assignees.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('Срок')} hint={t('В этот день задача появится у исполнителя в «Моих задачах»')} error={errors.due_at}>
            {({ id, invalid }) => (
              <Input id={id} invalid={invalid} type="date" value={form.due_date} onChange={e => set('due_date', e.target.value)} />
            )}
          </Field>
        </div>
        {branches.length > 1 && (
          <Field label={t('Филиал')} error={errors.branch}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.branch} onChange={e => set('branch', e.target.value)}>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
          </Field>
        )}
      </form>
    </Modal>
  )
}