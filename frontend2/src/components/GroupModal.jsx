import { useEffect, useState } from 'react'
import api from '../api/axios'
import { Avatar, Button, Field, Input, Modal, Select, apiErrorMessage, cn, useToast } from '../ui'

const listOf = response => response.data.results || response.data

/**
 * Создание и редактирование группы (TRU-87) — одна форма на список групп,
 * карточку и мастер онбординга. Архивные филиал и направление в выборе
 * только у группы, где они уже стоят (TRU-77) — сервер проверяет то же.
 */
export default function GroupModal({ group, onClose, onSaved }) {
  const isEdit = Boolean(group)
  const toast = useToast()
  const [form, setForm] = useState({
    name: group?.name || '',
    branch: group?.branch ? String(group.branch) : '',
    direction: group?.direction ? String(group.direction) : '',
    teachers: (group?.teachers || []).map(String),
    capacity: group?.capacity ?? 12,
    age_min: group?.age_min ?? '',
    age_max: group?.age_max ?? '',
    status: group?.status || 'active',
  })
  const [options, setOptions] = useState({ branches: [], directions: [], teachers: [] })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([api.get('branches/'), api.get('directions/'), api.get('users/', { params: { role: 'teacher' } })])
      .then(([b, d, t]) => setOptions({
        branches: listOf(b).filter(x => x.is_active || String(x.id) === String(group?.branch)),
        directions: listOf(d).filter(x => x.is_active || String(x.id) === String(group?.direction)),
        teachers: listOf(t),
      }))
      .catch(() => {})
  }, [group?.branch, group?.direction])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const toggleTeacher = id => set('teachers', form.teachers.includes(id) ? form.teachers.filter(x => x !== id) : [...form.teachers, id])

  // Направление доступно не во всех филиалах — показываем подходящие.
  const directions = form.branch
    ? options.directions.filter(d => !d.branches?.length || d.branches.map(String).includes(form.branch) || String(d.id) === form.direction)
    : options.directions

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    const payload = {
      ...form,
      capacity: Number(form.capacity),
      age_min: form.age_min === '' ? null : Number(form.age_min),
      age_max: form.age_max === '' ? null : Number(form.age_max),
    }
    try {
      const response = isEdit ? await api.patch(`groups/${group.id}/`, payload) : await api.post('groups/', payload)
      toast.success(isEdit ? 'Группа сохранена' : 'Группа создана')
      onSaved(response.data)
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
      size="lg"
      title={isEdit ? 'Редактировать группу' : 'Новая группа'}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" type="submit" form="group-form" loading={saving}>{isEdit ? 'Сохранить' : 'Создать группу'}</Button>
        </>
      }
    >
      <form id="group-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Название" required error={errors.name} className="sm:col-span-2">
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name} onChange={e => set('name', e.target.value)} placeholder="Например, Балет 4–6" required autoFocus />}
        </Field>
        <Field label="Филиал" required error={errors.branch}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.branch} onChange={e => set('branch', e.target.value)} required>
              <option value="">Выберите</option>
              {options.branches.map(b => <option key={b.id} value={b.id}>{b.name}{!b.is_active && ' (архив)'}</option>)}
            </Select>
          )}
        </Field>
        <Field label="Направление" required error={errors.direction}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.direction} onChange={e => set('direction', e.target.value)} required>
              <option value="">Выберите</option>
              {directions.map(d => <option key={d.id} value={d.id}>{d.name}{!d.is_active && ' (архив)'}</option>)}
            </Select>
          )}
        </Field>

        <Field label="Преподаватели" error={errors.teachers} className="sm:col-span-2" hint={options.teachers.length ? 'Можно выбрать нескольких' : 'Преподавателей пока нет — их заводит владелец или управляющий'}>
          <div className="flex flex-wrap gap-2">
            {options.teachers.map(t => {
              const active = form.teachers.includes(String(t.id))
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleTeacher(String(t.id))}
                  className={cn(
                    'inline-flex items-center gap-2 rounded-full border py-1 pl-1 pr-3 text-[13px] font-medium transition-colors',
                    active ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line text-ink-muted hover:border-line-strong hover:text-ink',
                  )}
                >
                  <Avatar name={t.full_name} className="size-6 text-[10px]" />
                  {t.full_name}
                </button>
              )
            })}
          </div>
        </Field>

        <Field label="Вместимость" required error={errors.capacity}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={1} max={100} value={form.capacity} onChange={e => set('capacity', e.target.value)} required />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Возраст от" error={errors.age_min}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_min} onChange={e => set('age_min', e.target.value)} />}
          </Field>
          <Field label="до" error={errors.age_max}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_max} onChange={e => set('age_max', e.target.value)} />}
          </Field>
        </div>
        {isEdit && (
          <Field label="Статус" error={errors.status}>
            {({ id }) => (
              <Select id={id} value={form.status} onChange={e => set('status', e.target.value)}>
                <option value="active">Набирает</option>
                <option value="paused">Приостановлена</option>
                <option value="closed">Закрыта</option>
              </Select>
            )}
          </Field>
        )}
      </form>
    </Modal>
  )
}
