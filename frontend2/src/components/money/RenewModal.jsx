import { useEffect, useState } from 'react'
import { renewSubscription } from '../../api/subscriptions'
import api from '../../api/axios'
import { addDays, toISODate } from '../../utils/calendarDate'
import { Button, Field, Input, Modal, Select, Skeleton, apiErrorMessage, formatDate, money, useToast } from '../../ui'
import { t } from '../../i18n'
import { MethodPicker } from './AcceptPaymentModal'

/**
 * Продать продление (TRU-69): тот же ребёнок, направление и филиал; тип —
 * прежний по умолчанию, оплата — полная цена. Новый абонемент связан со
 * старым (renewed_from) — задел под конверсию продлений.
 * row — строка экрана «Продления».
 */
export default function RenewModal({ row, onClose, onDone }) {
  const toast = useToast()
  const [types, setTypes] = useState(null)
  // Кончается по сроку — новый с дня после окончания; по занятиям — с сегодня.
  const startDefault = row.days_left <= 7 ? toISODate(addDays(new Date(`${row.ends_on}T00:00`), 1)) : toISODate(new Date())
  const [form, setForm] = useState({ subscription_type_id: row.subscription_type_id, starts_on: startDefault, paid_amount: '', payment_method: 'kaspi_transfer' })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('subscriptions/types/', { params: row.branch_id ? { branch: row.branch_id } : {} })
      .then(res => {
        setTypes(res.data)
        const current = res.data.find(tp => tp.id === row.subscription_type_id) || res.data[0]
        if (current) setForm(f => ({ ...f, subscription_type_id: current.id, paid_amount: String(Math.round(Number(current.price))) }))
      })
      .catch(err => { toast.error(apiErrorMessage(err)); setTypes([]) })
  }, [row.branch_id, row.subscription_type_id, toast])

  const type = types?.find(tp => tp.id === form.subscription_type_id)

  function pickType(id) {
    const next = types.find(tp => tp.id === id)
    setForm(f => ({ ...f, subscription_type_id: id, paid_amount: next ? String(Math.round(Number(next.price))) : f.paid_amount }))
  }

  async function submit(event) {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setErrors({})
    try {
      await renewSubscription(row.subscription_id, { ...form, paid_amount: form.paid_amount || 0 })
      toast.success(t('Продление оформлено: {name}', { name: row.child_name }))
      onDone()
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
      setSaving(false)
    }
  }

  const endsOn = type && form.starts_on ? toISODate(addDays(new Date(`${form.starts_on}T00:00`), type.duration_days)) : null

  return (
    <Modal
      open
      onClose={onClose}
      title={t('Продлить абонемент')}
      description={`${row.child_name} · ${row.direction_name}`}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="renew-form" loading={saving} disabled={!type}>{t('Продлить')}</Button>
        </>
      }
    >
      {types === null ? (
        <Skeleton className="h-48" />
      ) : types.length === 0 ? (
        <p className="py-4 text-center text-sm text-ink-muted">{t('В этом филиале нет абонементов для продажи. Заведите их в настройках.')}</p>
      ) : (
        <form id="renew-form" onSubmit={submit} className="flex flex-col gap-4">
          <p className="rounded-lg bg-surface-muted px-4 py-3 text-[13px] text-ink-muted">
            {t('Сейчас: {name}, до {date}', { name: row.subscription_name, date: formatDate(row.ends_on) })}
            {row.sessions_remaining != null && ` · ${t('осталось занятий: {n}', { n: row.sessions_remaining })}`}
          </p>
          <Field label={t('Новый абонемент')} required error={errors.subscription_type_id}>
            {({ id }) => (
              <Select id={id} value={form.subscription_type_id} onChange={e => pickType(e.target.value)}>
                {types.map(tp => <option key={tp.id} value={tp.id}>{tp.name} · {money(tp.price)}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('Начало')} required error={errors.starts_on} hint={endsOn ? t('Действует до {date}', { date: formatDate(endsOn) }) : null}>
            {({ id }) => <Input id={id} type="date" value={form.starts_on} onChange={e => setForm({ ...form, starts_on: e.target.value })} required />}
          </Field>
          <Field label={t('Оплачено сейчас, ₸')} error={errors.paid_amount} hint={t('0 — если оплатят позже: появится долг.')}>
            {({ id }) => <Input id={id} type="number" inputMode="numeric" min="0" value={form.paid_amount} onChange={e => setForm({ ...form, paid_amount: e.target.value })} />}
          </Field>
          {Number(form.paid_amount) > 0 && (
            <MethodPicker value={form.payment_method} onChange={payment_method => setForm({ ...form, payment_method })} />
          )}
          {errors.detail && <p className="text-sm text-danger-600">{errors.detail}</p>}
        </form>
      )}
    </Modal>
  )
}
