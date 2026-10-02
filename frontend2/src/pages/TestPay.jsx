import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'
import { CheckCircle2, FlaskConical } from 'lucide-react'
import { Button, Card, Skeleton, formatPhone, money } from '../ui'
import { t } from '../i18n'

/**
 * Тестовая оплата счёта (шлюз KASPI_PAY_GATEWAY=fake, только стенд):
 * так родитель увидел бы счёт в Kaspi. «Оплатить» делает то же, что
 * вебхук Kaspi, — в CRM появляется оплата, долг уменьшается. Без входа.
 */
export default function TestPay() {
  const { id } = useParams()
  const [invoice, setInvoice] = useState(null)
  const [state, setState] = useState('loading')
  const [paying, setPaying] = useState(false)
  const url = `/api/v1/payments/kaspi/test-pay/${encodeURIComponent(id)}/`

  useEffect(() => {
    axios.get(url)
      .then(res => { setInvoice(res.data); setState('ready') })
      .catch(() => setState('missing'))
  }, [url])

  async function pay() {
    setPaying(true)
    try {
      const res = await axios.post(url)
      setInvoice(res.data)
    } catch (err) {
      if (err.response?.data?.status) setInvoice(err.response.data)
    } finally {
      setPaying(false)
    }
  }

  return (
    <div className="flex min-h-screen items-start justify-center bg-surface-muted px-4 py-10 sm:items-center">
      <Card className="w-full max-w-sm space-y-5">
        <p className="flex items-center gap-2 rounded-md bg-warning-50 px-3 py-2 text-[13px] font-semibold text-warning-600">
          <FlaskConical className="size-4 shrink-0" />
          {t('Тестовая оплата: деньги не списываются')}
        </p>
        {state === 'loading' && <Skeleton className="h-40" />}
        {state === 'missing' && <p className="py-6 text-center text-sm text-ink-muted">{t('Счёт не найден')}</p>}
        {state === 'ready' && (
          <>
            <div className="text-center">
              <p className="text-sm text-ink-muted">{invoice.organization}</p>
              <p className="mt-1 text-3xl font-bold text-ink">{money(invoice.amount)}</p>
              <p className="mt-1 text-sm text-ink-muted">{invoice.child_name} · {invoice.subscription_name}</p>
              <p className="text-[13px] text-ink-subtle">{formatPhone(invoice.phone)}</p>
            </div>
            {invoice.status === 'paid' ? (
              <p className="flex items-center justify-center gap-2 text-base font-semibold text-success-600">
                <CheckCircle2 className="size-5" /> {t('Оплачено')}
              </p>
            ) : invoice.status === 'pending' ? (
              <Button variant="primary" className="w-full" loading={paying} onClick={pay}>
                {t('Оплатить {sum}', { sum: money(invoice.amount) })}
              </Button>
            ) : (
              <p className="text-center text-sm text-ink-muted">{t('Счёт уже не ждёт оплаты')}</p>
            )}
          </>
        )}
      </Card>
    </div>
  )
}
