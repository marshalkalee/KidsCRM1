import { useState } from 'react'
import api from '../api/axios'
import { Button, Checkbox, Field, Input, Modal, Textarea, apiErrorMessage, useToast } from '../ui'
import { WEEKDAYS, initialHours } from './workingHours'

export default function BranchModal({ branch, onClose, onSaved }) {
  const isEdit = Boolean(branch)
  const toast = useToast()
  const [form, setForm] = useState({
    name: branch?.name || '',
    address: branch?.address || '',
    phone: branch?.phone || '',
  })
  const [hours, setHours] = useState(() => initialHours(branch?.working_hours))
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const setDay = (code, patch) => setHours(h => ({ ...h, [code]: { ...h[code], ...patch } }))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    const working_hours = Object.fromEntries(Object.entries(hours).map(([code, day]) => [
      code, day.closed ? { closed: true } : { closed: false, open: day.open, close: day.close },
    ]))
    try {
      const payload = { ...form, working_hours }
      const response = isEdit ? await api.patch(`branches/${branch.id}/`, payload) : await api.post('branches/', payload)
      toast.success(isEdit ? 'Филиал сохранён' : 'Филиал добавлен')
      onSaved(response.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const hourErrors = errors.working_hours && typeof errors.working_hours === 'object' ? errors.working_hours : {}

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={isEdit ? 'Редактировать филиал' : 'Новый филиал'}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" type="submit" form="branch-form" loading={saving}>{isEdit ? 'Сохранить' : 'Создать филиал'}</Button>
        </>
      }
    >
      <form id="branch-form" onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label="Название" required error={errors.name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Центральный филиал" required autoFocus />}
        </Field>
        <Field label="Адрес" error={errors.address}>
          {({ id }) => <Textarea id={id} rows={2} value={form.address} onChange={e => setForm(f => ({ ...f, address: e.target.value }))} />}
        </Field>
        <Field label="Телефон" error={errors.phone}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} type="tel" value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} />}
        </Field>
        <div>
          <p className="font-btn mb-2.5 text-sm font-bold text-ink">Часы работы</p>
          <div className="flex flex-col gap-2">
            {WEEKDAYS.map(([code, , full]) => {
              const day = hours[code]
              return (
                <div key={code}>
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="font-btn w-[100px] shrink-0 text-xs text-[#374151]">{full}</span>
                    <Checkbox className="w-[90px] shrink-0 text-xs" label="Выходной" checked={day.closed} onChange={e => setDay(code, { closed: e.target.checked })} />
                    {!day.closed && (
                      <div className="flex items-center gap-1.5">
                        <Input type="time" aria-label={`${full}, открытие`} className="h-8 w-[100px] px-2 text-xs" value={day.open} onChange={e => setDay(code, { open: e.target.value })} />
                        <span className="text-ink-subtle">—</span>
                        <Input type="time" aria-label={`${full}, закрытие`} className="h-8 w-[100px] px-2 text-xs" value={day.close} onChange={e => setDay(code, { close: e.target.value })} />
                      </div>
                    )}
                  </div>
                  {hourErrors[code] && <p className="font-btn mt-1 text-[11px] text-danger-600">{[].concat(hourErrors[code])[0]}</p>}
                </div>
              )
            })}
          </div>
        </div>
      </form>
    </Modal>
  )
}
