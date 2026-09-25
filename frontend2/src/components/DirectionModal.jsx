import { useState } from 'react'
import api from '../api/axios'
import { Button, Field, Input, Modal, apiErrorMessage, cn, useToast } from '../ui'

// Готовые цвета для календаря — различимы между собой и с текстом поверх.
const PALETTE = ['#e8998d', '#c97b6e', '#f0b86e', '#8bc6a0', '#6fb1d8', '#8e9ae0', '#c48fd6', '#9aa3ad']

/** Направление: цвет в расписании, возраст, в каких филиалах доступно. */
export default function DirectionModal({ direction, branches, onClose, onSaved }) {
  const isEdit = Boolean(direction)
  const toast = useToast()
  const [form, setForm] = useState({
    name: direction?.name || '',
    color: direction?.color || PALETTE[0],
    age_min: direction?.age_min ?? '',
    age_max: direction?.age_max ?? '',
    branches: direction?.branches || [],
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const toggleBranch = branchId => set(
    'branches',
    form.branches.includes(branchId) ? form.branches.filter(x => x !== branchId) : [...form.branches, branchId],
  )

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    const payload = {
      ...form,
      age_min: form.age_min === '' ? null : Number(form.age_min),
      age_max: form.age_max === '' ? null : Number(form.age_max),
    }
    try {
      const response = isEdit ? await api.patch(`directions/${direction.id}/`, payload) : await api.post('directions/', payload)
      toast.success(isEdit ? 'Направление сохранено' : 'Направление добавлено')
      onSaved(response.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  // Архивные филиалы выбрать нельзя (сервер их не примет), но если
  // направление уже в таком филиале — показываем, чтобы не потерять.
  const options = branches.filter(b => b.is_active || form.branches.includes(b.id))

  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? 'Редактировать направление' : 'Новое направление'}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" type="submit" form="direction-form" loading={saving}>{isEdit ? 'Сохранить' : 'Добавить'}</Button>
        </>
      }
    >
      <form id="direction-form" onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Название" required error={errors.name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name} onChange={e => set('name', e.target.value)} placeholder="Например, Классический балет" required autoFocus />}
        </Field>

        <Field label="Цвет в расписании" error={errors.color}>
          <div className="flex flex-wrap items-center gap-2">
            {PALETTE.map(color => (
              <button
                key={color}
                type="button"
                aria-label={`Цвет ${color}`}
                aria-pressed={form.color === color}
                onClick={() => set('color', color)}
                className={cn('size-8 rounded-full ring-offset-2 transition', form.color === color ? 'ring-2 ring-ink' : 'hover:scale-110')}
                style={{ backgroundColor: color }}
              />
            ))}
            <label className="relative flex size-8 cursor-pointer items-center justify-center rounded-full border border-dashed border-line-strong text-xs text-ink-muted" title="Свой цвет">
              +
              <input type="color" className="absolute inset-0 cursor-pointer opacity-0" value={form.color} onChange={e => set('color', e.target.value)} />
            </label>
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Возраст от" error={errors.age_min}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_min} onChange={e => set('age_min', e.target.value)} />}
          </Field>
          <Field label="Возраст до" error={errors.age_max}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_max} onChange={e => set('age_max', e.target.value)} />}
          </Field>
        </div>

        <Field label="Доступно в филиалах" hint={options.length ? 'Можно выбрать несколько' : 'Сначала добавьте филиал'} error={errors.branches}>
          <div className="flex flex-wrap gap-2">
            {options.map(branch => {
              const active = form.branches.includes(branch.id)
              return (
                <button
                  key={branch.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleBranch(branch.id)}
                  className={cn(
                    'rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors',
                    active ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line text-ink-muted hover:border-line-strong hover:text-ink',
                  )}
                >
                  {branch.name}{!branch.is_active && ' (архив)'}
                </button>
              )
            })}
          </div>
        </Field>
      </form>
    </Modal>
  )
}
