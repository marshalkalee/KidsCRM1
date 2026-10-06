import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Pencil, Plus, Search, ShieldCheck, UsersRound } from 'lucide-react'
import api from '../api/axios'
import { ROLE_LABELS, useSession } from '../session/SessionContext'
import {
  Avatar, Badge, Button, CheckList, DataTable, EmptyState, Field, Input, Modal,
  PageHeader, SearchInput, Select, apiErrorMessage, cn, useToast,
} from '../ui'
import { personNameInput, personNameInputProps, phoneDigits, phoneInputProps } from '../utils/formValidation'
import { t } from '../i18n'

const ROLE_TONES = {
  owner: 'brand',
  manager: 'info',
  admin: 'success',
  teacher: 'warning',
  accountant: 'neutral',
}

const ALL_ROLES = ['owner', 'manager', 'admin', 'teacher', 'accountant']
const listOf = response => response.data.results || response.data

export default function Staff() {
  const navigate = useNavigate()
  const { user, can } = useSession()
  const toast = useToast()
  const [staff, setStaff] = useState(null)
  const [branches, setBranches] = useState([])
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)
  const [query, setQuery] = useState('')
  const [role, setRole] = useState('')

  const load = useCallback(() => {
    Promise.all([api.get('users/'), api.get('branches/')])
      .then(([users, branchList]) => {
        setStaff(listOf(users))
        setBranches(listOf(branchList).filter(branch => branch.is_active))
        setError(false)
      })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return (staff || []).filter(employee => {
      if (role && employee.role !== role) return false
      if (!needle) return true
      return `${employee.full_name} ${employee.phone}`.toLocaleLowerCase().includes(needle)
    })
  }, [staff, query, role])

  async function toggleActive(employee) {
    if (String(employee.id) === String(user?.id)) return
    try {
      await api.patch(`users/${employee.id}/`, { is_active: !employee.is_active })
      toast.success(employee.is_active ? t('Сотрудник отключён') : t('Сотрудник активирован'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const branchNames = Object.fromEntries(branches.map(branch => [String(branch.id), branch.name]))
  const canEdit = employee => can('can_manage_staff') && !(user?.role === 'manager' && employee.role === 'owner')
  const columns = [
    {
      key: 'full_name',
      header: t('Сотрудник'),
      primary: true,
      render: employee => (
        <span className="flex min-w-0 items-center gap-3">
          <Avatar name={employee.full_name} className="size-9 shrink-0" />
          <span className="min-w-0">
            <span className={cn('block truncate font-semibold', employee.is_active ? 'text-ink' : 'text-ink-muted')}>{employee.full_name}</span>
            <span className="block truncate text-xs text-ink-subtle">{employee.phone}</span>
          </span>
        </span>
      ),
    },
    { key: 'role', header: t('Роль'), mobileAside: true, render: employee => <Badge tone={ROLE_TONES[employee.role]}>{ROLE_LABELS[employee.role] || employee.role}</Badge> },
    {
      key: 'branches',
      header: t('Доступ к филиалам'),
      render: employee => employee.branches.length
        ? <span className="flex flex-wrap gap-1">{employee.branches.map(id => <Badge key={id}>{branchNames[String(id)] || t('Филиал')}</Badge>)}</span>
        : <span className="text-ink-muted">{t('Все филиалы')}</span>,
    },
    { key: 'status', header: t('Статус'), render: employee => <Badge dot tone={employee.is_active ? 'success' : 'neutral'}>{employee.is_active ? t('Активен') : t('Отключён')}</Badge> },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: employee => canEdit(employee) ? (
        <span className="inline-flex items-center gap-1" onClick={event => event.stopPropagation()}>
          <Button size="icon" variant="ghost" aria-label={t('Изменить')} onClick={() => setEditing(employee)}><Pencil className="size-4" /></Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={String(employee.id) === String(user?.id)}
            onClick={() => toggleActive(employee)}
          >
            {employee.is_active ? t('Отключить') : t('Включить')}
          </Button>
        </span>
      ) : null,
    },
  ]
  const activeCount = (staff || []).filter(employee => employee.is_active).length
  const teacherCount = (staff || []).filter(employee => employee.is_active && employee.role === 'teacher').length

  return (
    <div>
      <PageHeader
        title={t('Сотрудники')}
        description={staff ? t('{active} активных · {teachers} преподавателей', { active: activeCount, teachers: teacherCount }) : t('Загрузка…')}
        actions={(
          <>
            {/* Что роли видят сверх обычного (TRU-153) — только владелец. */}
            {can('can_manage_org_settings') && <Button to="/settings/access" icon={ShieldCheck}>{t('Доступ сотрудников')}</Button>}
            <Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новый сотрудник')}</Button>
          </>
        )}
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_240px]">
        <SearchInput value={query} onChange={setQuery} placeholder={t('Имя или телефон сотрудника')} />
        <Select value={role} onChange={event => setRole(event.target.value)} aria-label={t('Роль')}>
          <option value="">{t('Все роли')}</option>
          {ALL_ROLES.map(value => <option key={value} value={value}>{ROLE_LABELS[value]}</option>)}
        </Select>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        loading={!staff && !error}
        error={error}
        onRetry={load}
        onRowClick={employee => navigate(`/staff/${employee.id}`, { state: { from: '/settings/staff', label: t('Сотрудники') } })}
        empty={query || role ? (
          <EmptyState icon={Search} title={t('Сотрудники не найдены')} description={t('Измените поиск или фильтр по роли.')} />
        ) : (
          <EmptyState icon={UsersRound} title={t('Сотрудников пока нет')} description={t('Добавьте сотрудников и назначьте им роли и филиалы доступа.')} action={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новый сотрудник')}</Button>} />
        )}
      />

      {editing && (
        <StaffModal
          employee={editing === 'new' ? null : editing}
          actor={user}
          branches={branches}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }}
        />
      )}
    </div>
  )
}

function StaffModal({ employee, actor, branches, onClose, onSaved }) {
  const editing = Boolean(employee)
  const toast = useToast()
  const [form, setForm] = useState({
    full_name: employee?.full_name || '',
    phone: employee?.phone || '+7',
    role: employee?.role || 'admin',
    branches: (employee?.branches || []).map(String),
    password: '',
    is_active: employee?.is_active ?? true,
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))
  const ownCard = editing && String(employee.id) === String(actor?.id)
  const roles = actor?.role === 'owner' ? ALL_ROLES : ALL_ROLES.filter(value => value !== 'owner')

  async function submit(event) {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    const payload = {
      full_name: form.full_name.trim(),
      phone: form.phone,
      role: form.role,
      branches: form.branches,
      is_active: form.is_active,
    }
    if (form.password) payload.password = form.password
    try {
      if (editing) await api.patch(`users/${employee.id}/`, payload)
      else await api.post('users/', payload)
      toast.success(editing ? t('Сотрудник сохранён') : t('Сотрудник добавлен'))
      onSaved()
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? t('Редактировать сотрудника') : t('Новый сотрудник')}
      description={form.role === 'teacher' ? t('Преподаватель будет доступен в группах и расписании.') : t('Укажите роль и доступные сотруднику филиалы.')}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="staff-form" loading={saving}>{editing ? t('Сохранить') : t('Добавить сотрудника')}</Button>
        </>
      }
    >
      <form id="staff-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label={t('Имя и фамилия')} required error={errors.full_name} className="sm:col-span-2">
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.full_name} onChange={event => set('full_name', personNameInput(event.target.value))} required autoFocus {...personNameInputProps} />}
        </Field>
        <Field label={t('Телефон')} required error={errors.phone}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.phone} onChange={event => set('phone', phoneDigits(event.target.value))} required {...phoneInputProps} />}
        </Field>
        <Field label={t('Роль')} required error={errors.role}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.role} onChange={event => set('role', event.target.value)} required disabled={ownCard}>
              {roles.map(value => <option key={value} value={value}>{ROLE_LABELS[value]}</option>)}
            </Select>
          )}
        </Field>
        <Field
          label={editing ? t('Новый пароль') : t('Пароль для входа')}
          required={!editing}
          error={errors.password}
          hint={editing ? t('Оставьте пустым, чтобы не менять пароль.') : t('Не менее 8 символов.')}
          className="sm:col-span-2"
        >
          {({ id, invalid }) => <Input id={id} invalid={invalid} type="password" value={form.password} onChange={event => set('password', event.target.value)} minLength={8} maxLength={128} required={!editing} autoComplete="new-password" />}
        </Field>
        <Field label={t('Доступ к филиалам')} error={errors.branches} hint={t('Если ничего не выбрать, сотруднику доступны все филиалы.')} className="sm:col-span-2">
          <CheckList
            options={branches.map(branch => ({ value: String(branch.id), label: branch.name }))}
            value={form.branches}
            onChange={value => set('branches', value)}
            empty={t('Сначала добавьте филиал')}
          />
        </Field>
        {editing && (
          <Field label={t('Доступ в систему')} error={errors.is_active} className="sm:col-span-2">
            <label className={cn('flex items-center justify-between gap-4 rounded-md border border-line p-3', ownCard && 'opacity-60')}>
              <span>
                <span className="block text-sm font-semibold text-ink">{t('Сотрудник активен')}</span>
                <span className="block text-xs text-ink-muted">{ownCard ? t('Нельзя отключить собственную учётную запись.') : t('Отключённый сотрудник не сможет войти в систему.')}</span>
              </span>
              <input type="checkbox" checked={form.is_active} disabled={ownCard} onChange={event => set('is_active', event.target.checked)} className="size-4 accent-[var(--color-brand-600)]" />
            </label>
          </Field>
        )}
      </form>
    </Modal>
  )
}
