import { useState } from 'react'
import api from '../api/axios'
import { Button, Field, Input, Modal, Textarea, apiErrorMessage, cn, useToast } from '../ui'
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
          <Button variant="primary" type="submit" form="branch-form" loading={saving}>{isEdit ? 'Сохранить' : 'Добавить'}</Button>
        </>
      }
    >
      <form id="branch-form" onSubmit={submit} className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Название" required error={errors.name}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Например, Центральный" required autoFocus />}
          </Field>
          <Field label="Телефон" error={errors.phone}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="tel" value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} />}
          </Field>
        </div>
        <Field label="Адрес" error={errors.address}>
          {({ id }) => <Textarea id={id} rows={2} value={form.address} onChange={e => setForm(f => ({ ...f, address: e.target.value }))} />}
        </Field>

        <Field label="Часы работы">
          <div className="divide-y divide-line rounded-lg border border-line">
            {WEEKDAYS.map(([code, short, full]) => {
              const day = hours[code]
              return (
                <div key={code} className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="w-8 text-sm font-semibold text-ink" title={full}>{short}</span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={!day.closed}
                      aria-label={`${full}: ${day.closed ? 'выходной' : 'рабочий день'}`}
                      onClick={() => setDay(code, { closed: !day.closed })}
                      className={cn('relative h-5 w-9 shrink-0 rounded-full transition-colors', day.closed ? 'bg-line-strong' : 'bg-brand-600')}
                    >
                      <span className={cn('absolute top-0.5 size-4 rounded-full bg-white shadow transition-all', day.closed ? 'left-0.5' : 'left-[18px]')} />
                    </button>
                    {day.closed ? (
                      <span className="text-sm text-ink-subtle">Выходной</span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <Input type="time" aria-label={`${full}, открытие`} className="h-9 w-28" value={day.open} onChange={e => setDay(code, { open: e.target.value })} />
                        <span className="text-ink-subtle">—</span>
                        <Input type="time" aria-label={`${full}, закрытие`} className="h-9 w-28" value={day.close} onChange={e => setDay(code, { close: e.target.value })} />
                      </div>
                    )}
                  </div>
                  {hourErrors[code] && <p className="mt-1 text-xs text-danger-600">{[].concat(hourErrors[code])[0]}</p>}
                </div>
              )
            })}
          </div>
        </Field>
      </form>
    </Modal>
  )
}
