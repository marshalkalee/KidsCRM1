import { useEffect, useState } from 'react'
import api from '../api/axios'
import { Button, Field, Input, Modal, MultiSelect, Select, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'

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
      .then(([b, d, tch]) => setOptions({
        branches: listOf(b).filter(x => x.is_active || String(x.id) === String(group?.branch)),
        directions: listOf(d).filter(x => x.is_active || String(x.id) === String(group?.direction)),
        teachers: listOf(tch),
      }))
      .catch(() => {})
  }, [group?.branch, group?.direction])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

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
      toast.success(isEdit ? t('Группа сохранена') : t('Группа создана'))
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
      title={isEdit ? t('Редактировать группу') : t('Новая группа')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="group-form" loading={saving}>{isEdit ? t('Сохранить') : t('Создать группу')}</Button>
        </>
      }
    >
      <form id="group-form" onSubmit={submit} className="grid gap-3.5 sm:grid-cols-2">
        <Field label={t('Название')} required error={errors.name} className="sm:col-span-2">
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name} onChange={e => set('name', e.target.value)} placeholder={t('Балет — Младшая группа')} required autoFocus />}
        </Field>
        <Field label={t('Филиал')} required error={errors.branch}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.branch} onChange={e => set('branch', e.target.value)} required>
              <option value="">{t('Выберите')}</option>
              {options.branches.map(b => <option key={b.id} value={b.id}>{b.name}{!b.is_active && t(' (архив)')}</option>)}
            </Select>
          )}
        </Field>
        <Field label={t('Направление')} required error={errors.direction}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.direction} onChange={e => set('direction', e.target.value)} required>
              <option value="">{t('Выберите')}</option>
              {directions.map(d => <option key={d.id} value={d.id}>{d.name}{!d.is_active && t(' (архив)')}</option>)}
            </Select>
          )}
        </Field>

        <Field label={t('Преподаватели')} error={errors.teachers} className="sm:col-span-2">
          {({ id, invalid }) => (
            <MultiSelect
              id={id}
              invalid={invalid}
              value={form.teachers}
              onChange={v => set('teachers', v)}
              options={options.teachers.map(tch => ({ value: String(tch.id), label: tch.full_name }))}
              placeholder={options.teachers.length ? t('Не назначены') : t('Преподавателей нет')}
            />
          )}
        </Field>

        <div className="grid grid-cols-3 gap-3.5 sm:col-span-2">
          <Field label={t('Вместимость')} required error={errors.capacity}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={1} max={100} value={form.capacity} onChange={e => set('capacity', e.target.value)} required />}
          </Field>
          <Field label={t('Возраст от')} error={errors.age_min}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_min} onChange={e => set('age_min', e.target.value)} />}
          </Field>
          <Field label={t('Возраст до')} error={errors.age_max}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_max} onChange={e => set('age_max', e.target.value)} />}
          </Field>
        </div>
        <Field label={t('Статус')} error={errors.status} className="sm:col-span-2">
          {({ id }) => (
            <Select id={id} value={form.status} onChange={e => set('status', e.target.value)} required>
              <option value="active">{t('Набирает')}</option>
              <option value="paused">{t('Приостановлена')}</option>
              <option value="closed">{t('Закрыта')}</option>
            </Select>
          )}
        </Field>
      </form>
    </Modal>
  )
}
