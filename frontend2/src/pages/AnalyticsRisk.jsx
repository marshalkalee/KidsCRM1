import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CalendarX, CircleDollarSign, ClipboardPlus, MessageCircle, Phone, ShieldAlert, TicketCheck } from 'lucide-react'
import api from '../api/axios'
import { AnalyticsNav, AnalyticsToolbar, ExportButton, useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet } from '../components/analytics'
import { Badge, Button, Card, ErrorState, PageHeader, Skeleton, apiErrorMessage, cn, formatDate, money, useToast } from '../ui'
import { t } from '../i18n'

const SIGNALS = {
  attendance: { icon: CalendarX, label: 'Участились пропуски', tone: 'danger' },
  subscription: { icon: TicketCheck, label: 'Абонемент заканчивается или истёк', tone: 'warning' },
  debt: { icon: CircleDollarSign, label: 'Есть задолженность', tone: 'warning' },
}

export default function AnalyticsRisk() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const report = useAnalyticsGet('risk-list', '', filters)
  const data = report.data

  return (
    <>
      <PageHeader
        title={t('Риск-лист «в зоне ухода»')}
        description={t('Семьи, которым стоит позвонить до того, как они перестанут ходить')}
        actions={<ExportButton report="risk_list" filters={filters} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      {report.error && !data ? (
        <Card><ErrorState onRetry={report.reload} /></Card>
      ) : !data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[1, 2, 3, 4].map(item => <Skeleton key={item} className="h-28" />)}</div>
      ) : (
        <div className={cn(report.loading && 'opacity-60 transition-opacity')}>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Summary icon={ShieldAlert} label={t('В зоне риска')} value={data.summary.total} />
            <Summary icon={AlertTriangle} label={t('Срочно связаться')} value={data.summary.urgent} danger />
            <Summary icon={CalendarX} label={t('С участившимися пропусками')} value={data.summary.signals.attendance} />
            <Summary icon={TicketCheck} label={t('С финансовыми сигналами')} value={data.summary.financial} />
          </div>

          <Card className="mb-5 flex flex-col gap-2 bg-info-50/50 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-semibold text-ink">{t('Один сигнал — внимание, два или три — срочно')}</p>
              <p className="mt-1 text-sm text-ink-muted">
                {t('Список занимает {share}% активной базы. Порог роста пропусков: {change} п.п., минимум {count}.', {
                  share: data.summary.share_percent,
                  change: data.thresholds.absence_change_pp,
                  count: data.thresholds.minimum_absences,
                })}
                {data.retrospective.departed > 0 && ` ${t('Ретропроверка: {caught} из {total} ушедших имели бы хотя бы один сигнал.', { caught: data.retrospective.caught, total: data.retrospective.departed })}`}
              </p>
            </div>
            <Link to="/settings/organization" className="shrink-0 text-sm font-semibold text-brand-600 hover:text-brand-700">{t('Настроить пороги')}</Link>
          </Card>

          {data.items.length ? (
            <div className="grid gap-4 xl:grid-cols-2">
              {data.items.map(item => <RiskCard key={item.id} item={item} filters={filters} />)}
            </div>
          ) : (
            <Card className="py-12 text-center">
              <ShieldAlert className="mx-auto mb-3 size-9 text-success-600" />
              <p className="font-semibold text-ink">{t('По выбранным условиям детей в зоне риска нет')}</p>
              <p className="mt-1 text-sm text-ink-muted">{t('Смените период или филиал, чтобы проверить другую выборку.')}</p>
            </Card>
          )}
        </div>
      )}
    </>
  )
}

function Summary({ icon: Icon, label, value, danger = false }) {
  return (
    <Card>
      <div className={cn('mb-3 flex size-9 items-center justify-center rounded-md', danger ? 'bg-danger-50 text-danger-600' : 'bg-brand-50 text-brand-600')}><Icon className="size-4.5" /></div>
      <p className="text-xl font-bold text-ink">{value}</p>
      <p className="mt-1 text-xs text-ink-muted">{label}</p>
    </Card>
  )
}

function RiskCard({ item, filters }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const query = filters.query ? `?${filters.query}` : ''

  async function createTask() {
    setBusy(true)
    try {
      const { data } = await api.post(`analytics/risk-list/${item.id}/task/${query}`)
      toast.success(data.created ? t('Задача удержания создана') : t('Задача удержания уже существует'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const phone = item.phone || item.whatsapp
  const whatsapp = (item.whatsapp || item.phone || '').replace(/\D/g, '')
  return (
    <Card className={cn('border-l-4', item.level === 'urgent' ? 'border-l-danger-500' : 'border-l-warning-500')}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/children/${item.id}`} className="text-lg font-bold text-ink hover:text-brand-600">{item.name}</Link>
          <p className="mt-1 text-sm text-ink-muted">{[item.branch, item.direction, item.parent].filter(Boolean).join(' · ') || t('Контакты и группа не указаны')}</p>
        </div>
        <Badge tone={item.level === 'urgent' ? 'danger' : 'warning'}>{item.level === 'urgent' ? t('Срочно') : t('Внимание')}</Badge>
      </div>

      <div className="space-y-2">
        {item.signals.map(key => <Signal key={key} signal={key} item={item} />)}
      </div>

      <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4">
        <Button icon={ClipboardPlus} size="sm" loading={busy} onClick={createTask}>{t('Создать задачу')}</Button>
        {phone && <a href={`tel:${phone}`} className="font-btn inline-flex h-8 items-center gap-1.5 rounded-md border-[1.5px] border-line-strong px-3.5 text-xs font-semibold text-ink-muted hover:border-brand-300"><Phone className="size-4" />{t('Позвонить')}</a>}
        {whatsapp && <a href={`https://wa.me/${whatsapp}`} target="_blank" rel="noreferrer" className="font-btn inline-flex h-8 items-center gap-1.5 rounded-md bg-success-50 px-3.5 text-xs font-semibold text-success-600"><MessageCircle className="size-4" />WhatsApp</a>}
      </div>
    </Card>
  )
}

function Signal({ signal, item }) {
  const meta = SIGNALS[signal]
  const Icon = meta.icon
  let detail = ''
  if (signal === 'attendance') detail = t('{count} пропусков, на {change} п.п. выше личной нормы', { count: item.attendance.absences, change: item.attendance.absence_change_pp })
  if (signal === 'subscription') detail = item.subscription.state === 'expired' ? t('Абонемент истёк') : t('Заканчивается {date}', { date: formatDate(item.subscription.ends_on) })
  if (signal === 'debt') detail = money(item.debt)
  return (
    <div className="flex items-start gap-3 rounded-md bg-page px-3 py-2.5">
      <Icon className={cn('mt-0.5 size-4 shrink-0', meta.tone === 'danger' ? 'text-danger-600' : 'text-warning-600')} />
      <div><p className="text-sm font-semibold text-ink">{t(meta.label)}</p><p className="text-xs text-ink-muted">{detail}</p></div>
    </div>
  )
}
