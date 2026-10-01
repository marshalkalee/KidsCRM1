import { useCallback, useEffect, useState } from 'react'
import { Plus, Wallet } from 'lucide-react'
import { cancelPayment, fetchChildDebt, fetchChildPayments } from '../../api/payments'
import { useSession } from '../../session/SessionContext'
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Modal, Skeleton, Textarea,
  apiErrorMessage, formatDateTime, money, useToast,
} from '../../ui'
import { t } from '../../i18n'
import AcceptPaymentModal from './AcceptPaymentModal'
import { PendingInvoices } from './KaspiInvoice'

/** Вкладка «Оплаты» (TRU-70, TRU-67): долг, «Принять оплату», счета Kaspi в ожидании, история с отменёнными. */
export default function PaymentsTab({ child, onCountChange }) {
  const { can } = useSession()
  const canAccept = can('can_accept_payments')
  const [payments, setPayments] = useState(null)
  const [debt, setDebt] = useState(null)
  const [error, setError] = useState(false)
  const [accepting, setAccepting] = useState(false)
  const [cancelling, setCancelling] = useState(null)
  const [invoicesKey, setInvoicesKey] = useState(0)

  const load = useCallback(() => {
    Promise.all([fetchChildPayments(child.id), fetchChildDebt(child.id)])
      .then(([rows, debtValue]) => {
        setPayments(rows)
        setDebt(debtValue)
        setError(false)
        onCountChange?.(rows.length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])

  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (payments === null) return <Skeleton className="h-40" />

  const owes = Number(debt) > 0

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[13px] text-ink-muted">{t('Текущая задолженность')}</p>
          <p className={owes ? 'text-xl font-bold text-danger-600' : 'text-xl font-bold text-success-600'}>{money(debt)}</p>
        </div>
        {canAccept && (
          <Button variant="primary" icon={Plus} onClick={() => setAccepting(true)}>{t('Принять оплату')}</Button>
        )}
      </Card>

      <PendingInvoices child={child} reloadKey={invoicesKey} onChanged={load} />

      {payments.length === 0 ? (
        <Card><EmptyState icon={Wallet} title={t('Оплат пока нет')} /></Card>
      ) : (
        <div className="space-y-2">
          {payments.map(p => (
            <Card key={p.id} className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className={p.deleted_at ? 'flex items-center gap-2 font-semibold text-ink-subtle' : 'flex items-center gap-2 font-semibold text-ink'}>
                  {money(p.amount)}
                  <span className="text-[13px] font-normal text-ink-muted">{t(p.method_display)}</span>
                  {p.deleted_at && <Badge tone="danger">{t('Отменено')}</Badge>}
                </p>
                <p className="text-[13px] text-ink-muted">
                  {formatDateTime(p.paid_at)} · {t('принял {name}', { name: p.received_by_name })}
                </p>
                {p.comment && <p className="text-[13px] text-ink-muted">{p.comment}</p>}
                {p.cancelled_reason && <p className="text-[13px] text-danger-600">{t('Причина отмены: {reason}', { reason: p.cancelled_reason })}</p>}
              </div>
              {canAccept && !p.deleted_at && (
                <Button variant="ghost" size="sm" onClick={() => setCancelling(p)}>{t('Отменить')}</Button>
              )}
            </Card>
          ))}
        </div>
      )}

      {accepting && (
        <AcceptPaymentModal child={child} onClose={() => setAccepting(false)} onPaid={load} onInvoiced={() => setInvoicesKey(k => k + 1)} />
      )}
      {cancelling && (
        <CancelPaymentModal payment={cancelling} onClose={() => setCancelling(null)} onDone={() => { setCancelling(null); load() }} />
      )}
    </div>
  )
}

/** Отмена — с причиной; оплата остаётся в истории как отменённая. */
function CancelPaymentModal({ payment, onClose, onDone }) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setSaving(true)
    try {
      await cancelPayment(payment.id, reason.trim())
      toast.success(t('Оплата отменена'))
      onDone()
    } catch (err) {
      toast.error(apiErrorMessage(err))
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={t('Отменить оплату {sum}?', { sum: money(payment.amount) })}
      description={t('Оплата останется в истории как отменённая, долг вырастет.')}
      footer={
        <>
          <Button onClick={onClose}>{t('Не отменять')}</Button>
          <Button variant="danger" type="submit" form="cancel-payment-form" loading={saving} disabled={!reason.trim()}>
            {t('Отменить оплату')}
          </Button>
        </>
      }
    >
      <form id="cancel-payment-form" onSubmit={submit}>
        <Field label={t('Причина отмены')} required>
          {({ id }) => <Textarea id={id} value={reason} onChange={e => setReason(e.target.value)} autoFocus rows={2} placeholder={t('Например, ошиблись суммой')} />}
        </Field>
      </form>
    </Modal>
  )
}
