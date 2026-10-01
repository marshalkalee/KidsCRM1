import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Copy, MessageCircle, Send, Smartphone } from 'lucide-react'
import { cancelPaymentRequest, confirmPaymentRequest, fetchPaymentRequests } from '../../api/payments'
import { useSession } from '../../session/SessionContext'
import { Badge, Button, Card, Modal, apiErrorMessage, formatDateTime, formatPhone, money, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'

/**
 * Удалённая оплата через Kaspi (backend: payments/remote.py). Счёт — ещё не
 * оплата: долг уменьшится, когда деньги придут (вебхук Kaspi или кнопка
 * «Оплата пришла»).
 */

/** Текст для родителя + «Открыть WhatsApp» / «Копировать». */
export function InvoiceShare({ request }) {
  const toast = useToast()

  async function copy() {
    try {
      await navigator.clipboard.writeText(request.message)
      toast.success(t('Скопировано'))
    } catch {
      toast.error(t('Не удалось скопировать'))
    }
  }

  return (
    <div className="space-y-3">
      <p className="whitespace-pre-line rounded-lg bg-surface-muted px-4 py-3 text-sm text-ink">{request.message}</p>
      <div className="flex flex-wrap gap-2">
        {request.whatsapp_url && (
          <a
            href={request.whatsapp_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-10 items-center gap-2 rounded-md bg-success-600 px-4 text-sm font-semibold text-white hover:brightness-95"
          >
            <MessageCircle className="size-4" /> {t('Открыть WhatsApp')}
          </a>
        )}
        <Button icon={Copy} onClick={copy}>{t('Копировать')}</Button>
      </div>
    </div>
  )
}

/** Итог «Счёт выставлен»: куда ушёл и что дальше. */
export function InvoiceSentModal({ request, onClose }) {
  const gateway = request.channel === 'gateway'
  return (
    <Modal open onClose={onClose} title={t('Счёт выставлен')} footer={<Button variant="primary" onClick={onClose}>{t('Готово')}</Button>}>
      <div className="space-y-4">
        <div className="flex flex-col items-center gap-2 text-center">
          <Send className="size-10 text-brand-600" />
          <p className="text-2xl font-bold text-ink">{money(request.amount)}</p>
          <p className="text-sm text-ink-muted">{request.child_name} · {request.subscription_name}</p>
        </div>
        <p className="rounded-lg border border-line px-4 py-3 text-sm text-ink-muted">
          {gateway
            ? t('Счёт отправлен в Kaspi на номер {phone}. Когда родитель оплатит, оплата появится сама, долг уменьшится.', { phone: formatPhone(request.phone) })
            : t('Отправьте родителю сообщение. Когда деньги придут в Kaspi, нажмите «Оплата пришла» во вкладке «Оплаты» — до этого долг не меняется.')}
        </p>
        <InvoiceShare request={request} />
      </div>
    </Modal>
  )
}

const STATUS_TONES = { pending: 'warning', paid: 'success', cancelled: 'neutral', expired: 'neutral', failed: 'danger' }

/** Счета ребёнка, которые ждут оплаты, — во вкладке «Оплаты». */
export function PendingInvoices({ child, reloadKey, onChanged }) {
  const { can } = useSession()
  const canAccept = can('can_accept_payments')
  const toast = useToast()
  const confirm = useConfirm()
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(null)
  const [sharing, setSharing] = useState(null)

  const load = useCallback(() => {
    fetchPaymentRequests(child.id, 'pending').then(setRows).catch(() => setRows([]))
  }, [child.id])

  useEffect(() => { load() }, [load, reloadKey])

  async function paid(request) {
    const ok = await confirm({
      title: t('Оплата {sum} пришла?', { sum: money(request.amount) }),
      message: t('Проверьте поступление в Kaspi. Оплата запишется на абонемент, долг уменьшится.'),
      confirmText: t('Да, деньги пришли'),
    })
    if (!ok) return
    setBusy(request.id)
    try {
      await confirmPaymentRequest(request.id)
      toast.success(t('Оплата записана'))
      load()
      onChanged?.()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function cancel(request) {
    const ok = await confirm({
      title: t('Отменить счёт {sum}?', { sum: money(request.amount) }),
      message: t('Если родитель уже заплатил, не отменяйте — нажмите «Оплата пришла».'),
      confirmText: t('Отменить счёт'),
      danger: true,
    })
    if (!ok) return
    setBusy(request.id)
    try {
      await cancelPaymentRequest(request.id)
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  if (rows.length === 0) return null

  return (
    <div className="space-y-2">
      {rows.map(r => (
        <Card key={r.id} className="flex flex-wrap items-center justify-between gap-3 bg-warning-50/40">
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 font-semibold text-ink">
              <Smartphone className="size-4 text-ink-muted" />
              {t('Счёт Kaspi')} {money(r.amount)}
              <Badge tone={STATUS_TONES[r.status]} dot>{t(r.status_display)}</Badge>
            </p>
            <p className="text-[13px] text-ink-muted">
              {r.subscription_name} · {formatPhone(r.phone)} · {t('выставлен {date}', { date: formatDateTime(r.created_at) })}
            </p>
            {r.expires_at && <p className="text-[13px] text-ink-muted">{t('Действует до {date}', { date: formatDateTime(r.expires_at) })}</p>}
          </div>
          {canAccept && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="ghost" onClick={() => setSharing(r)}>{t('Сообщение')}</Button>
              <Button size="sm" variant="ghost" disabled={busy === r.id} onClick={() => cancel(r)}>{t('Отменить')}</Button>
              <Button size="sm" variant="primary" icon={CheckCircle2} loading={busy === r.id} onClick={() => paid(r)}>{t('Оплата пришла')}</Button>
            </div>
          )}
        </Card>
      ))}
      {sharing && (
        <Modal open onClose={() => setSharing(null)} title={t('Сообщение родителю')} footer={<Button onClick={() => setSharing(null)}>{t('Закрыть')}</Button>}>
          <InvoiceShare request={sharing} />
        </Modal>
      )}
    </div>
  )
}

/** Когда некуда платить: без шлюза нужны реквизиты Kaspi центра. */
export function KaspiNotConfigured() {
  const { can } = useSession()
  return (
    <div className="rounded-lg bg-warning-50 px-4 py-3 text-sm text-ink">
      <p className="font-semibold">{t('Не указано, куда платить через Kaspi')}</p>
      <p className="mt-1 text-ink-muted">
        {can('can_manage_org_settings')
          ? <>{t('Добавьте ссылку Kaspi Pay или номер для перевода в')} <Link to="/settings/organization" className="font-semibold text-brand-600 hover:underline">{t('настройках организации')}</Link>.</>
          : t('Попросите владельца добавить ссылку Kaspi Pay или номер для перевода в настройках организации.')}
      </p>
    </div>
  )
}
