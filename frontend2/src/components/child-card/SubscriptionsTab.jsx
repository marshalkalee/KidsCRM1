import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarClock, CheckCircle2, CreditCard, Layers, MapPin, Wallet } from 'lucide-react'
import api from '../../api/axios'
import {
  Badge, Card, EmptyState, ErrorState, Skeleton, cn, formatDate, money,
} from '../../ui'
import { plural, t } from '../../i18n'

const STATUS_META = {
  active: { label: 'Активен', tone: 'success' },
  frozen: { label: 'Заморожен', tone: 'info' },
  expired: { label: 'Истёк', tone: 'neutral' },
  exhausted: { label: 'Исчерпан', tone: 'warning' },
}

export default function SubscriptionsTab({ child, onCountChange }) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    api.get('subscriptions/', { params: { child_id: child.id } })
      .then(response => {
        const items = response.data.results || response.data
        setRows(items)
        onCountChange?.(items.length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])

  useEffect(() => { load() }, [load])

  const summary = useMemo(() => {
    if (!rows) return null
    const active = rows.filter(item => item.status === 'active')
    return {
      active: active.length,
      debt: rows.reduce((sum, item) => sum + Number(item.debt || 0), 0),
      remaining: active.reduce((sum, item) => sum + Number(item.sessions_remaining_cache || 0), 0),
    }
  }, [rows])

  if (error) return <Card><ErrorState onRetry={() => { setError(false); setRows(null); load() }} /></Card>
  if (!rows) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24" />
        <div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-64" /><Skeleton className="h-64" /></div>
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={CreditCard}
          title={t('Абонементов пока нет')}
          description={t('После продажи из заявки абонемент появится здесь автоматически.')}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryTile icon={CheckCircle2} label={t('Активные')} value={summary.active} tone="success" />
        <SummaryTile icon={CalendarClock} label={t('Осталось занятий')} value={summary.remaining} />
        <SummaryTile icon={Wallet} label={t('Общий долг')} value={money(summary.debt)} tone={summary.debt > 0 ? 'danger' : 'success'} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {rows.map(subscription => <SubscriptionCard key={subscription.id} subscription={subscription} />)}
      </div>
    </div>
  )
}

function SummaryTile({ icon: Icon, label, value, tone = 'brand' }) {
  const tones = {
    brand: 'bg-brand-50 text-brand-600',
    success: 'bg-success-50 text-success-600',
    danger: 'bg-danger-50 text-danger-600',
  }
  return (
    <Card className="flex items-center gap-3 !p-4">
      <span className={cn('rounded-lg p-2.5', tones[tone])}><Icon className="size-5" /></span>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{label}</p>
        <p className="mt-0.5 text-xl font-bold text-ink">{value}</p>
      </div>
    </Card>
  )
}

function SubscriptionCard({ subscription }) {
  const meta = STATUS_META[subscription.status] || { label: subscription.status_label, tone: 'neutral' }
  const paid = Number(subscription.paid)
  const price = Number(subscription.price)
  const debt = Number(subscription.debt)
  const paymentPercent = price > 0 ? Math.min(100, Math.round((paid / price) * 100)) : 100
  const remaining = subscription.sessions_remaining_cache
  const quota = subscription.quota_sessions
  const usagePercent = !subscription.is_unlimited && quota
    ? Math.max(0, Math.min(100, Math.round((Number(remaining || 0) / quota) * 100)))
    : 100

  return (
    <Card className="overflow-hidden !p-0">
      <div className="flex flex-col gap-4 border-b border-line px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-bold text-ink">{subscription.name}</h3>
            <Badge tone={meta.tone}>{t(meta.label)}</Badge>
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            {formatDate(subscription.starts_on)}–{formatDate(subscription.ends_on)}
          </p>
        </div>
        <p className="shrink-0 text-lg font-bold text-ink">{money(subscription.price)}</p>
      </div>

      <div className="space-y-5 px-5 py-4">
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-ink-muted">
          <span className="inline-flex items-center gap-1.5"><Layers className="size-4 text-ink-subtle" />{subscription.direction_name}</span>
          {subscription.branch_name && <span className="inline-flex items-center gap-1.5"><MapPin className="size-4 text-ink-subtle" />{subscription.branch_name}</span>}
        </div>

        <Progress
          label={t('Остаток занятий')}
          value={subscription.is_unlimited ? t('Безлимит') : t('{n} из {total}', { n: remaining ?? 0, total: quota })}
          percent={usagePercent}
          tone="brand"
        />
        <Progress
          label={t('Оплата')}
          value={debt > 0 ? t('Оплачено {paid}, долг {debt}', { paid: money(paid), debt: money(debt) }) : t('Оплачено полностью')}
          percent={paymentPercent}
          tone={debt > 0 ? 'danger' : 'success'}
        />

        {Number(subscription.discount_amount) > 0 && (
          <div className="rounded-lg bg-surface-muted px-3 py-2 text-sm text-ink-muted">
            {t('Скидка')}: <span className="font-semibold text-ink">{money(subscription.discount_amount)}</span>
            {subscription.discount_reason_label && ` · ${t(subscription.discount_reason_label)}`}
            {subscription.discount_comment && <p className="mt-0.5 text-xs text-ink-subtle">{subscription.discount_comment}</p>}
          </div>
        )}
        <p className="text-xs text-ink-subtle">
          {subscription.is_unlimited
            ? t('Абонемент без ограничения количества занятий')
            : t('Номинал: {n} {word}', { n: quota, word: plural(quota, ['занятие', 'занятия', 'занятий']) })}
        </p>
      </div>
    </Card>
  )
}

function Progress({ label, value, percent, tone }) {
  const color = tone === 'danger' ? 'bg-danger-600' : tone === 'success' ? 'bg-success-600' : 'bg-brand-500'
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3 text-sm">
        <span className="text-ink-muted">{label}</span>
        <span className="text-right font-semibold text-ink">{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}
