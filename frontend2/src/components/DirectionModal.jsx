import { useState } from 'react'
import api from '../api/axios'
import { Button, CheckList, Field, Input, Modal, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'

/** Направление: цвет в расписании, возраст, в каких филиалах доступно. */
export default function DirectionModal({ direction, branches, onClose, onSaved }) {
  const isEdit = Boolean(direction)
  const toast = useToast()
  const [form, setForm] = useState({
    name: direction?.name || '',
    color: direction?.color || '#e8998d',
    age_min: direction?.age_min ?? '',
    age_max: direction?.age_max ?? '',
    branches: (direction?.branches || []).map(String),
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

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
      toast.success(isEdit ? t('Направление сохранено') : t('Направление добавлено'))
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
      size="sm"
      title={isEdit ? t('Редактировать направление') : t('Новое направление')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="direction-form" loading={saving}>{isEdit ? t('Сохранить') : t('Создать направление')}</Button>
        </>
      }
    >
      <form id="direction-form" onSubmit={submit} className="flex flex-col gap-3.5">
        <div className="flex gap-3.5">
          <Field label={t('Название направления')} required error={errors.name} className="flex-1">
            {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name} onChange={e => set('name', e.target.value)} placeholder={t('Балет')} required autoFocus />}
          </Field>
          <Field label={t('Цвет')} error={errors.color} className="w-[90px]">
            {({ id }) => <Input id={id} type="color" className="cursor-pointer p-1" value={form.color} onChange={e => set('color', e.target.value)} />}
          </Field>
        </div>
        <div className="flex gap-3.5">
          <Field label={t('Возраст от')} error={errors.age_min} className="flex-1">
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_min} onChange={e => set('age_min', e.target.value)} />}
          </Field>
          <Field label={t('Возраст до')} error={errors.age_max} className="flex-1">
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={99} value={form.age_max} onChange={e => set('age_max', e.target.value)} />}
          </Field>
        </div>
        <Field label={t('Доступно в филиалах')} error={errors.branches}>
          <CheckList
            empty={t('Нет активных филиалов')}
            options={options.map(b => ({ value: b.id, label: b.is_active ? b.name : t('{name} (архив)', { name: b.name }) }))}
            value={form.branches}
            onChange={v => set('branches', v)}
          />
        </Field>
      </form>
    </Modal>
  )
}
