import { useEffect, useState } from 'react'
import api from '../api/axios'
import { Button, Checkbox, DateInput, Field, Input, Modal, Select, Textarea, apiErrorMessage, cn, useToast } from '../ui'

const EMPTY = {
  full_name: '',
  birth_date: '',
  gender: '',
  status: 'active',
  directions: [],
  medical_notes: '',
  consent_given: false,
  leave_reason: '',
}

function initialForm(child) {
  if (!child) return EMPTY
  return Object.fromEntries(Object.keys(EMPTY).map(key => [key, child[key] ?? EMPTY[key]]))
}

/**
 * Создание (child не передан) и редактирование ребёнка. Проверки — на
 * сервере (ChildSerializer: дата не в будущем, причина ухода для «Ушёл»,
 * допустимые переходы статуса); ошибки показываются у своих полей.
 */
export default function ChildModal({ child, onClose, onSaved }) {
  const isEdit = Boolean(child)
  const toast = useToast()
  const [form, setForm] = useState(() => initialForm(child))
  const [directions, setDirections] = useState([])
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('directions/').then(r => setDirections(r.data.results || r.data)).catch(() => {})
  }, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const toggleDirection = id => set(
    'directions',
    form.directions.includes(id) ? form.directions.filter(x => x !== id) : [...form.directions, id],
  )

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const response = isEdit
        ? await api.patch(`clients/children/${child.id}/`, form)
        : await api.post('clients/children/', form)
      toast.success(isEdit ? 'Изменения сохранены' : 'Ребёнок добавлен')
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
      title={isEdit ? 'Редактировать ребёнка' : 'Новый ребёнок'}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" type="submit" form="child-form" loading={saving}>
            {isEdit ? 'Сохранить' : 'Создать ребёнка'}
          </Button>
        </>
      }
    >
      <form id="child-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label="ФИО" required error={errors.full_name}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} value={form.full_name} onChange={e => set('full_name', e.target.value)} placeholder="Введите ФИО" required autoFocus />
          )}
        </Field>
        <Field label="Дата рождения" required error={errors.birth_date}>
          {({ id, invalid }) => (
            <DateInput id={id} invalid={invalid} value={form.birth_date} onChange={v => set('birth_date', v)} required />
          )}
        </Field>
        <Field label="Пол" required error={errors.gender}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.gender} onChange={e => set('gender', e.target.value)} required>
              <option value="">Выберите</option>
              <option value="female">Девочка</option>
              <option value="male">Мальчик</option>
            </Select>
          )}
        </Field>
        <Field label="Статус" error={errors.status}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.status} onChange={e => set('status', e.target.value)}>
              <option value="active">Активен</option>
              <option value="paused">Приостановлен</option>
              <option value="left">Ушёл</option>
            </Select>
          )}
        </Field>
        {form.status === 'left' ? (
          <Field label="Причина ухода" required error={errors.leave_reason} className="sm:col-span-2">
            {({ id, invalid }) => (
              <Input id={id} invalid={invalid} value={form.leave_reason} onChange={e => set('leave_reason', e.target.value)} required />
            )}
          </Field>
        ) : null}

        {directions.length > 0 && (
          <Field label="Направления" error={errors.directions} className="sm:col-span-2">
            <div className="flex flex-wrap gap-2">
              {directions.map(direction => {
                const active = form.directions.includes(direction.id)
                return (
                  <button
                    key={direction.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => toggleDirection(direction.id)}
                    className={cn(
                      'font-btn rounded-[20px] border px-3.5 py-1.5 text-xs font-medium transition-colors',
                      active ? 'border-brand-400 bg-brand-50 text-brand-600' : 'border-[#e5e7eb] bg-[#f8f9ff] text-ink-muted hover:text-ink',
                    )}
                  >
                    {direction.name}
                  </button>
                )
              })}
            </div>
          </Field>
        )}

        <Field label="Медицинские заметки" error={errors.medical_notes} className="sm:col-span-2">
          {({ id }) => <Textarea id={id} value={form.medical_notes} onChange={e => set('medical_notes', e.target.value)} placeholder="Аллергии, особенности..." />}
        </Field>
        <Checkbox
          className="sm:col-span-2"
          label="Согласие на обработку персональных данных получено"
          checked={form.consent_given}
          onChange={e => set('consent_given', e.target.checked)}
        />
        {errors.non_field_errors && <p className="text-sm text-danger-600 sm:col-span-2">{errors.non_field_errors[0]}</p>}
      </form>
    </Modal>
  )
}
