import { useCallback, useEffect, useState } from 'react'
import { Wallet } from 'lucide-react'
import { cancelPayment, fetchChildDebt, fetchChildPayments, recordPayment } from '../../api/payments'
import { fetchChildSubscriptions } from '../../api/subscriptions'
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Input, Select, Skeleton,
  apiErrorMessage, formatDateTime, money, useConfirm, useToast,
} from '../../ui'

const METHODS = [
  { value: 'kaspi_transfer', label: 'Kaspi-перевод' },
  { value: 'cash', label: 'Наличные' },
  { value: 'card', label: 'Карта' },
  { value: 'other', label: 'Другое' },
]

export default function PaymentsTab({ child, onCountChange }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [payments, setPayments] = useState(null)
  const [debt, setDebt] = useState(null)
  const [subscriptions, setSubscriptions] = useState([])
  const [error, setError] = useState(false)
  const [form, setForm] = useState({ subscription: '', amount: '', method: 'kaspi_transfer', comment: '' })
  const [submitting, setSubmitting] = useState(false)

  const load = useCallback(() => {
    Promise.all([fetchChildPayments(child.id), fetchChildDebt(child.id), fetchChildSubscriptions(child.id)])
      .then(([paymentRows, debtValue, subs]) => {
        const active = subs.filter(s => s.status === 'active' || s.status === 'frozen')
        setPayments(paymentRows)
        setDebt(debtValue)
        setSubscriptions(active)
        setForm(f => (f.subscription ? f : { ...f, subscription: active[0]?.id || '', amount: debtValue || '' }))
        setError(false)
        onCountChange?.(paymentRows.length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])

  useEffect(() => { load() }, [load])

  async function submit(e) {
    e.preventDefault()
    if (submitting) return
    setSubmitting(true)
    try {
      await recordPayment({ subscription: form.subscription, amount: form.amount, method: form.method, comment: form.comment })
      toast.success('Оплата принята')
      setForm({ subscription: '', amount: '', method: 'kaspi_transfer', comment: '' })
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function cancel(payment) {
    const ok = await confirm({ title: 'Отменить оплату?', message: 'Понадобится причина отмены.', confirmText: 'Отменить' })
    if (!ok) return
    const reason = window.prompt('Причина отмены')
    if (!reason) return
    try {
      await cancelPayment(payment.id, reason)
      toast.success('Оплата отменена')
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (payments === null) return <Skeleton className="h-40" />

  return (
    <div className="space-y-4">
      <Card className="flex items-center justify-between">
        <span className="text-ink-muted">Текущая задолженность</span>
        <span className="text-lg font-semibold text-ink">{money(debt)}</span>
      </Card>

      {subscriptions.length > 0 && (
        <form onSubmit={submit}>
          <Card className="space-y-3">
            <p className="font-semibold text-ink">Принять оплату</p>
            <Field label="Абонемент">
              {({ id }) => (
                <Select id={id} value={form.subscription} onChange={e => setForm({ ...form, subscription: e.target.value })}>
                  {subscriptions.map(s => <option key={s.id} value={s.id}>{s.subscription_type_name}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Сумма" required>
              {({ id }) => (
                <Input id={id} type="number" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} required />
              )}
            </Field>
            <Field label="Способ">
              {({ id }) => (
                <Select id={id} value={form.method} onChange={e => setForm({ ...form, method: e.target.value })}>
                  {METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Комментарий">
              {({ id }) => <Input id={id} value={form.comment} onChange={e => setForm({ ...form, comment: e.target.value })} />}
            </Field>
            <Button type="submit" variant="primary" loading={submitting}>Принять оплату</Button>
          </Card>
        </form>
      )}

      {payments.length === 0 ? (
        <Card><EmptyState icon={Wallet} title="Оплат пока нет" /></Card>
      ) : (
        <div className="space-y-2">
          {payments.map(p => (
            <Card key={p.id} className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-semibold text-ink flex items-center gap-2">
                  {money(p.amount)}
                  {p.deleted_at && <Badge tone="danger">Отменено</Badge>}
                </p>
                <p className="text-[13px] text-ink-muted">
                  {formatDateTime(p.paid_at)} · принял {p.received_by_name}
                </p>
                {p.cancelled_reason && <p className="text-[13px] text-ink-muted">Причина: {p.cancelled_reason}</p>}
              </div>
              {!p.deleted_at && (
                <Button variant="ghost" size="sm" onClick={() => cancel(p)}>Отменить</Button>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}