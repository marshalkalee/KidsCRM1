import { useEffect, useRef, useState } from 'react'
import { Baby, Inbox, X } from 'lucide-react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import { Button, DateInput, Field, Input, Modal, Select, Textarea, apiErrorMessage, cn, useToast } from '../../ui'
import { t } from '../../i18n'
import { MANUAL_TYPES } from './types'

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const listOf = data => data?.results || data || []

/**
 * Новая задача со страницы «Задачи» (TRU-181): поручение без ребёнка и
 * заявки («подготовить костюмы») или по ним. Исполнители и филиалы — только
 * те, что видит сотрудник (сервер режет по его филиалам, Д36).
 */
export default function NewTaskModal({ onClose, onCreated }) {
  const { user, branches, activeBranchId } = useSession()
  const toast = useToast()
  const [staff, setStaff] = useState([])
  const [form, setForm] = useState(() => ({
    title: '',
    type: 'other',
    due_date: todayIso(),
    due_time: '',
    assigned_to: String(user.id),
    branch: activeBranchId ? String(activeBranchId) : branches.length === 1 ? String(branches[0].id) : '',
    description: '',
  }))
  const [subject, setSubject] = useState(null)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('users/')
      .then(res => setStaff(listOf(res.data).filter(u => ['owner', 'manager', 'admin'].includes(u.role) && u.is_active !== false)))
      .catch(() => {})
  }, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  async function submit(e) {
    e.preventDefault()
    if (saving) return
    setSaving(true)
    setErrors({})
    try {
      const time = form.due_time || '23:59'
      await api.post('tasks/', {
        title: form.title.trim(),
        type: form.type,
        description: form.description.trim(),
        assigned_to: form.assigned_to || null,
        branch: form.branch || null,
        child: subject?.kind === 'child' ? subject.id : null,
        lead: subject?.kind === 'lead' ? subject.id : null,
        due_at: form.due_date ? new Date(`${form.due_date}T${time}:00`).toISOString() : null,
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
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="new-task-form" loading={saving}>{t('Создать')}</Button>
        </>
      }
    >
      <form id="new-task-form" onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t('Что сделать')} required error={errors.title}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} autoFocus required maxLength={255} value={form.title} onChange={e => set('title', e.target.value)} placeholder={t('Например: подготовить костюмы к концерту')} />
          )}
        </Field>
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Field label={t('Тип задачи')} error={errors.type}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.type} onChange={e => set('type', e.target.value)}>
                {MANUAL_TYPES.map(type => <option key={type.value} value={type.value}>{type.label}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('Исполнитель')} error={errors.assigned_to}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.assigned_to} onChange={e => set('assigned_to', e.target.value)}>
                {assignees.map(person => (
                  <option key={person.id} value={String(person.id)}>
                    {String(person.id) === String(user.id) ? t('Я ({name})', { name: person.full_name }) : person.full_name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t('Срок')} error={errors.due_at}>
            {({ id, invalid }) => <DateInput id={id} invalid={invalid} value={form.due_date} onChange={value => set('due_date', value)} />}
          </Field>
          <Field label={t('Время')} hint={t('Пусто — до конца дня')}>
            {({ id }) => <Input id={id} type="time" value={form.due_time} onChange={e => set('due_time', e.target.value)} />}
          </Field>
        </div>
        <Field label={t('О ком')} hint={t('Необязательно: ребёнок или заявка')} error={errors.child || errors.lead}>
          {({ id }) => <SubjectPicker id={id} value={subject} onChange={setSubject} />}
        </Field>
        {branches.length > 1 && (
          <Field label={t('Филиал')} error={errors.branch}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.branch} onChange={e => set('branch', e.target.value)}>
                <option value="">{t('Без филиала')}</option>
                {branches.map(branch => <option key={branch.id} value={String(branch.id)}>{branch.name}</option>)}
              </Select>
            )}
          </Field>
        )}
        <Field label={t('Подробности')} error={errors.description}>
          {({ id, invalid }) => <Textarea id={id} invalid={invalid} rows={3} value={form.description} onChange={e => set('description', e.target.value)} />}
        </Field>
      </form>
    </Modal>
  )
}

/** Поиск ребёнка или заявки по имени — выбранное стоит чипом с крестиком. */
function SubjectPicker({ id, value, onChange }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const timer = useRef(null)

  useEffect(() => {
    window.clearTimeout(timer.current)
    const text = query.trim()
    if (text.length < 2) return undefined
    timer.current = window.setTimeout(() => {
      Promise.all([
        api.get('clients/children/table/', { params: { q: text, page_size: 5 } }).catch(() => ({ data: { results: [] } })),
        api.get('leads/', { params: { q: text, page_size: 5 } }).catch(() => ({ data: { results: [] } })),
      ]).then(([children, leads]) => setResults([
        ...listOf(children.data).slice(0, 5).map(c => ({ kind: 'child', id: c.id, name: c.full_name })),
        ...listOf(leads.data).slice(0, 5).map(l => ({ kind: 'lead', id: l.id, name: l.child_name || l.parent_name, hint: l.parent_name })),
      ]))
    }, 250)
    return () => window.clearTimeout(timer.current)
  }, [query])

  // Короткий запрос — подсказок нет (старые результаты не показываем).
  const shown = query.trim().length < 2 ? [] : results

  if (value) {
    return (
      <div className="flex">
        <span className="inline-flex h-[38px] items-center gap-2 rounded-md bg-brand-50 px-3 text-[13px] font-semibold text-brand-700">
          {value.kind === 'child' ? <Baby className="size-4" /> : <Inbox className="size-4" />}
          {value.name}
          <span className="font-normal text-brand-600">· {value.kind === 'child' ? t('ребёнок') : t('заявка')}</span>
          <button type="button" onClick={() => onChange(null)} aria-label={t('Убрать')} className="ml-1 rounded p-0.5 hover:bg-brand-100">
            <X className="size-3.5" />
          </button>
        </span>
      </div>
    )
  }

  return (
    <div>
      <Input id={id} value={query} onChange={e => setQuery(e.target.value)} placeholder={t('Начните вводить имя')} autoComplete="off" />
      {shown.length > 0 && (
        <ul className="mt-1.5 max-h-56 overflow-y-auto rounded-lg border border-line bg-surface py-1">
          {shown.map(item => (
            <li key={`${item.kind}-${item.id}`}>
              <button
                type="button"
                onClick={() => { onChange(item); setQuery(''); setResults([]) }}
                className={cn('flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] hover:bg-surface-muted')}
              >
                {item.kind === 'child' ? <Baby className="size-4 text-ink-subtle" /> : <Inbox className="size-4 text-ink-subtle" />}
                <span className="font-semibold text-ink">{item.name}</span>
                <span className="text-ink-subtle">{item.kind === 'child' ? t('ребёнок') : t('заявка')}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
