import { useEffect, useState } from 'react'
import { Banknote, CheckCircle2, CreditCard, Send, Smartphone, Store, Wallet } from 'lucide-react'
import { createPaymentRequest, fetchPaymentRequestOptions, recordPayment } from '../../api/payments'
import { fetchChildSubscriptions } from '../../api/subscriptions'
import { Button, Field, Input, Modal, Select, Skeleton, apiErrorMessage, cn, money, useToast } from '../../ui'
import { t } from '../../i18n'
import { phoneDigits, phoneInputProps } from '../../utils/formValidation'
import { InvoiceSentModal, KaspiNotConfigured } from './KaspiInvoice'

// Kaspi первым — самый частый случай у стойки (ТЗ п. 10.4).
const METHODS = [
  { value: 'kaspi_transfer', icon: Smartphone, get label() { return t('Kaspi') } },
  { value: 'cash', icon: Banknote, get label() { return t('Наличные') } },
  { value: 'card', icon: CreditCard, get label() { return t('Карта') } },
  { value: 'other', icon: Wallet, get label() { return t('Другое') } },
]

// Ключ одного приёма оплаты: повторный клик или повтор при плохой связи
// уходят с тем же ключом, и сервер вернёт ту же оплату, а не создаст вторую.
function newKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c =>
    (Number(c) ^ (Math.random() * 16) >> (Number(c) / 4)).toString(16))
}

const hasDebt = s => Number(s.debt) > 0

// Как платят: здесь и сейчас — или удалённо, счётом в Kaspi.
const MODES = [
  { value: 'desk', icon: Store, get label() { return t('Принять сейчас') } },
  { value: 'remote', icon: Send, get label() { return t('Счёт в Kaspi') } },
]

/**
 * «Принять оплату» (TRU-67): сумма по умолчанию — долг по абонементу,
 * способ — кнопками, после оплаты — итог «оплачено / осталось».
 * Режим «Счёт в Kaspi» — удалённая оплата: счёт родителю на телефон или
 * сообщение с реквизитами центра; долг уменьшится, когда деньги придут.
 * subscriptionId — какой абонемент выбрать сразу (экран «Задолженности»).
 */
export default function AcceptPaymentModal({ child, subscriptionId, onClose, onPaid, onInvoiced }) {
  const toast = useToast()
  const [subscriptions, setSubscriptions] = useState(null)
  const [form, setForm] = useState({ subscription: '', amount: '', method: 'kaspi_transfer', comment: '' })
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [key] = useState(newKey)
  const [result, setResult] = useState(null)
  const [mode, setMode] = useState('desk')
  const [remote, setRemote] = useState(null)
  const [phone, setPhone] = useState('')
  const [invoiceKey] = useState(newKey)
  const [invoice, setInvoice] = useState(null)

  // Канал и телефон плательщика — когда впервые открыли «Счёт в Kaspi».
  useEffect(() => {
    if (mode !== 'remote' || remote) return
    fetchPaymentRequestOptions(child.id)
      .then(options => { setRemote(options); setPhone(options.phone || '') })
      .catch(err => { toast.error(apiErrorMessage(err)); setMode('desk') })
  }, [mode, remote, child.id, toast])

  useEffect(() => {
    fetchChildSubscriptions(child.id)
      .then(rows => {
        // Платят за долг (он бывает и у истёкшего) или за действующий абонемент.
        const payable = rows.filter(s => hasDebt(s) || s.status === 'active' || s.status === 'frozen')
        payable.sort((a, b) => Number(hasDebt(b)) - Number(hasDebt(a)))
        setSubscriptions(payable)
        const first = payable.find(s => s.id === subscriptionId) || payable[0]
        if (first) setForm(f => ({ ...f, subscription: first.id, amount: hasDebt(first) ? String(Math.round(Number(first.debt))) : '' }))
      })
      .catch(err => { toast.error(apiErrorMessage(err)); setSubscriptions([]) })
  }, [child.id, subscriptionId, toast])

  const selected = subscriptions?.find(s => s.id === form.subscription)

  function pick(subscription) {
    setForm(f => ({ ...f, subscription: subscription.id, amount: hasDebt(subscription) ? String(Math.round(Number(subscription.debt))) : '' }))
  }

  async function submit(event) {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setErrors({})
    try {
      if (mode === 'remote') {
        const request = await createPaymentRequest({
          subscription: form.subscription, amount: form.amount, phone, idempotency_key: invoiceKey,
        })
        setInvoice(request)
        onInvoiced?.(request)
      } else {
        const payment = await recordPayment({ ...form, idempotency_key: key })
        setResult(payment)
        onPaid?.(payment)
      }
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (invoice) return <InvoiceSentModal request={invoice} onClose={onClose} />

  const remoteBlocked = mode === 'remote' && (!remote || !remote.ready)
  const submitLabel = mode === 'remote'
    ? (form.amount ? t('Выставить счёт {sum}', { sum: money(form.amount) }) : t('Выставить счёт'))
    : (form.amount ? t('Принять {sum}', { sum: money(form.amount) }) : t('Принять оплату'))

  if (result) {
    const left = Number(result.subscription_debt)
    return (
      <Modal open onClose={onClose} title={t('Оплата принята')} footer={<Button variant="primary" onClick={onClose}>{t('Готово')}</Button>}>
        <div className="flex flex-col items-center gap-3 py-2 text-center">
          <CheckCircle2 className="size-12 text-success-600" />
          <p className="text-2xl font-bold text-ink">{money(result.amount)}</p>
          <p className="text-sm text-ink-muted">{child.full_name} · {t(result.method_display)}</p>
          <div className="mt-1 w-full rounded-lg bg-surface-muted px-4 py-3 text-sm">
            <p className={cn('font-semibold', left > 0 ? 'text-warning-600' : 'text-success-600')}>
              {left > 0 ? t('По абонементу осталось: {sum}', { sum: money(left) }) : t('Абонемент оплачен полностью')}
            </p>
            {Number(result.child_debt) !== left && (
              <p className="mt-1 text-ink-muted">{t('Общий долг ребёнка: {sum}', { sum: money(result.child_debt) })}</p>
            )}
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={t('Принять оплату')}
      description={child.full_name}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="accept-payment-form" loading={submitting} disabled={!selected || remoteBlocked}>
            {submitLabel}
          </Button>
        </>
      }
    >
      {subscriptions === null ? (
        <Skeleton className="h-48" />
      ) : subscriptions.length === 0 ? (
        <p className="py-4 text-center text-sm text-ink-muted">{t('Нет абонемента, за который можно принять оплату. Сначала продайте абонемент.')}</p>
      ) : (
        <form id="accept-payment-form" onSubmit={submit} className="flex flex-col gap-4">
          <ChoicePicker options={MODES} value={mode} onChange={setMode} label={t('Как платят')} columns="grid-cols-2" />

          {subscriptions.length > 1 ? (
            <Field label={t('Абонемент')} error={errors.subscription}>
              {({ id }) => (
                <Select id={id} value={form.subscription} onChange={e => pick(subscriptions.find(s => s.id === e.target.value))}>
                  {subscriptions.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.subscription_type_name}{hasDebt(s) ? ` · ${t('долг {sum}', { sum: money(s.debt) })}` : ''}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          ) : (
            <div className="rounded-lg bg-surface-muted px-4 py-3 text-sm">
              <p className="font-semibold text-ink">{selected.subscription_type_name}</p>
              <p className="text-ink-muted">
                {hasDebt(selected) ? t('Долг: {sum}', { sum: money(selected.debt) }) : t('Долга нет — оплата пойдёт вперёд')}
              </p>
            </div>
          )}

          <Field label={t('Сумма, ₸')} required error={errors.amount}>
            {({ id, invalid }) => (
              <Input
                id={id}
                invalid={invalid}
                type="number"
                inputMode="numeric"
                min="1"
                step="1"
                value={form.amount}
                onChange={e => setForm({ ...form, amount: e.target.value })}
                className="text-base font-semibold"
                required
                autoFocus
              />
            )}
          </Field>

          {mode === 'desk' ? (
            <MethodPicker value={form.method} onChange={method => setForm({ ...form, method })} />
          ) : remote === null ? (
            <Skeleton className="h-16" />
          ) : !remote.ready ? (
            <KaspiNotConfigured />
          ) : (
            <Field
              label={t('Телефон родителя в Kaspi')}
              required
              error={errors.phone}
              hint={remote.channel === 'gateway'
                ? t('Счёт придёт в приложение Kaspi.kz на этот номер')
                : t('На этот номер откроется WhatsApp с сообщением об оплате')}
            >
              {({ id, invalid }) => (
                <Input id={id} invalid={invalid} value={phone} onChange={e => setPhone(phoneDigits(e.target.value))} required {...phoneInputProps} />
              )}
            </Field>
          )}

          {mode === 'desk' && (
            <Field label={t('Комментарий')} error={errors.comment}>
              {({ id }) => <Input id={id} value={form.comment} onChange={e => setForm({ ...form, comment: e.target.value })} placeholder={t('Необязательно')} />}
            </Field>
          )}
        </form>
      )}
    </Modal>
  )
}

/** Способ оплаты кнопками, Kaspi первым — и в оплате, и в продаже продления. */
export function MethodPicker({ value, onChange, label = t('Способ') }) {
  return <ChoicePicker options={METHODS} value={value} onChange={onChange} label={label} />
}

function ChoicePicker({ options, value, onChange, label, columns = 'grid-cols-2 sm:grid-cols-4' }) {
  return (
    <div className="flex flex-col gap-[5px]">
      <p className="font-btn text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{label}</p>
      <div role="radiogroup" aria-label={label} className={cn('grid gap-2', columns)}>
        {options.map(m => {
          const active = value === m.value
          return (
            <button
              key={m.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(m.value)}
              className={cn(
                'flex h-11 items-center justify-center gap-1.5 rounded-md border-[1.5px] text-[13px] font-semibold transition',
                active ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line-strong text-ink-muted hover:border-brand-200',
              )}
            >
              <m.icon className="size-4" />
              {m.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
