import { useState } from 'react'
import { Info, TriangleAlert } from 'lucide-react'
import { Card, CardHeader, DataTable, EmptyState, ErrorState, PageHeader, Skeleton, Tabs, formatDate } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ChartCard, DonutChart, ExportButton, MetricTile, MultiLineChart, PALETTE,
  RankBars, StackedBars, breakdownLabel, formatValue, useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
  useMetrics,
} from '../components/analytics'

const CHECK_TILES = ['average_check', 'sales_count', 'discount_total']
const DIMENSIONS = [
  { key: 'branch', get label() { return t('Филиалы') } },
  { key: 'direction', get label() { return t('Направления') } },
  { key: 'subscription_type', get label() { return t('Типы абонементов') } },
  { key: 'source', get label() { return t('Источники клиентов') } },
  { key: 'client', get label() { return t('Новые и продления') } },
]
const AGE_KEYS = ['0_30', '31_60', 'over_60']
const AGE_COLORS = ['var(--color-info-600)', 'var(--color-warning-600)', 'var(--color-danger-600)']
// Среднее дальше медианы больше чем на столько — его тянут выбросы.
const SKEW_PERCENT = 15

function changePercent(current, previous) {
  if (current == null || previous == null || Number(previous) === 0) return null
  return Math.round(((Number(current) - Number(previous)) / Number(previous)) * 1000) / 10
}

/** Плитка из готовой цифры отчёта, а не из реестра метрик. */
function tile(value, unit, { previous, kind = 'event' } = {}) {
  return {
    value, unit, kind, previous: previous ?? null,
    change_percent: changePercent(value, previous), enough_data: true,
  }
}

/**
 * «Чек и долги» (TRU-124, ТЗ раздел 7). Средний чек — средняя цена
 * проданного абонемента; рядом медиана и распределение, чтобы один годовой
 * абонемент не исказил вывод, и влияние скидок. Долг — та же цифра, что
 * экран «Задолженности», за прошлые даты — сохранённые снимки.
 */
export default function AnalyticsCheckDebt() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const metrics = useMetrics(CHECK_TILES, filters)
  const check = useAnalyticsGet('average-check', '', filters)
  const debt = useAnalyticsGet('debt', '', filters)

  return (
    <>
      <PageHeader title={t('Аналитика')} description={t('Средний чек и задолженности')} actions={<ExportButton report="check_debt" filters={filters} />} />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={metrics.data?.period} previous={metrics.data?.previous_period} />
      <CheckSection metrics={metrics} check={check} />
      <DebtSection debt={debt} />
    </>
  )
}

function CheckSection({ metrics, check }) {
  const [dimension, setDimension] = useState('branch')
  const data = check.data
  const values = metrics.data?.metrics || {}
  const summary = data?.summary
  const median = summary && tile(summary.median, 'money', { previous: data.previous.median })
  const skew = summary?.median && summary.average
    ? Math.round(((Number(summary.average) - Number(summary.median)) / Number(summary.median)) * 100)
    : 0
  const common = { loading: check.loading, error: check.error, onRetry: check.reload, metric: data ? tile(summary.count, 'count') : null }

  if (metrics.error && check.error) return <Card className="mb-6"><ErrorState onRetry={check.reload} /></Card>

  return (
    <section className="mb-8">
      <h2 className="mb-3 text-lg font-bold text-ink">{t('Средний чек')}</h2>
      <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricTile name="average_check" metric={values.average_check} loading={metrics.loading} />
        <MetricTile name="median_check" metric={median} loading={check.loading} />
        <MetricTile name="sales_count" metric={values.sales_count} loading={metrics.loading} />
        <MetricTile name="discount_total" metric={values.discount_total} loading={metrics.loading} />
      </div>

      <p className="mb-4 flex items-start gap-2 rounded-lg border border-info-50 bg-info-50/40 px-4 py-3 text-[13px] text-ink-muted">
        <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
        {t('Средний чек — средняя цена проданного абонемента со скидкой, по дате продажи. Медиана — середина: половина абонементов дешевле, половина дороже. Один дорогой абонемент сдвигает среднее, но не медиану.')}
      </p>
      {Math.abs(skew) >= SKEW_PERCENT && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-warning-50 bg-warning-50/50 px-4 py-3 text-[13px] text-ink">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-600" />
          {skew > 0
            ? t('Среднее выше медианы на {n}%: его тянут вверх несколько дорогих абонементов. Для решений смотрите на медиану и распределение.', { n: skew })
            : t('Среднее ниже медианы на {n}%: его тянут вниз несколько дешёвых абонементов. Для решений смотрите на медиану и распределение.', { n: -skew })}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard className="lg:col-span-2" title={t('Средний чек и медиана по месяцам')} description={t('12 месяцев до конца периода')} {...common} empty={!data?.monthly.some(m => m.count)}>
          <MultiLineChart
            unit="money"
            granularity="month"
            lines={[
              { key: 'average', label: t('Средний чек'), series: (data?.monthly || []).map(m => ({ date: m.month, value: m.average })) },
              { key: 'median', label: t('Медиана'), series: (data?.monthly || []).map(m => ({ date: m.month, value: m.median })) },
            ]}
          />
        </ChartCard>
        <ChartCard autoHeight title={t('Распределение цен')} description={t('Сколько абонементов продано в каждом интервале')} {...common} empty={!data?.distribution.length}>
          <PriceBars bins={data?.distribution} summary={summary} />
        </ChartCard>
      </div>

      <Card padded={false} className="mt-4">
        <div className="p-5 pb-0">
          <CardHeader title={t('Средний чек в разрезах')} description={t('Медиана рядом со средним: если они сильно расходятся, в группе есть выбросы')} />
          <Tabs tabs={DIMENSIONS} value={dimension} onChange={setDimension} className="mb-1" />
        </div>
        <CheckTable rows={data?.by[dimension]} loading={check.loading && !data} error={check.error} onRetry={check.reload} />
      </Card>

      <DiscountsCard data={data} common={common} />
    </section>
  )
}

function PriceBars({ bins: all, summary }) {
  // Пустые интервалы между ценами не показываем: абонементы продаются по нескольким ценам.
  const bins = (all || []).filter(b => b.count > 0)
  const max = Math.max(...bins.map(b => b.count), 1)
  return (
    <div>
      <ol className="space-y-2.5">
        {bins.map(bin => (
          <li key={bin.from}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="text-ink">{formatValue(bin.from, 'money')} – {formatValue(bin.to, 'money')}</span>
              <span className="shrink-0 font-semibold text-ink">
                {formatValue(bin.count, 'count')}
                <span className="ml-1.5 text-xs font-normal text-ink-subtle">{formatValue(bin.share, 'percent')}</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full" style={{ width: `${(bin.count / max) * 100}%`, background: PALETTE[1] }} />
            </div>
          </li>
        ))}
      </ol>
      {summary?.count > 0 && (
        <p className="mt-4 text-xs text-ink-subtle">
          {t('Половина абонементов — от {low} до {high}', { low: formatValue(summary.p25, 'money'), high: formatValue(summary.p75, 'money') })}
        </p>
      )}
    </div>
  )
}

function CheckTable({ rows, loading, error, onRetry }) {
  const columns = [
    { key: 'label', header: t('Название'), primary: true, render: row => breakdownLabel(row) },
    { key: 'count', header: t('Продано'), align: 'right', mobileAside: true, render: row => formatValue(row.count, 'count') },
    { key: 'average', header: t('Средний чек'), align: 'right', render: row => <span className="font-semibold text-ink">{formatValue(row.average, 'money')}</span> },
    { key: 'median', header: t('Медиана'), align: 'right', render: row => formatValue(row.median, 'money') },
    { key: 'amount', header: t('Сумма'), align: 'right', render: row => formatValue(row.amount, 'money') },
  ]
  return (
    <DataTable
      columns={columns}
      rows={rows || []}
      rowKey={row => row.key ?? 'none'}
      loading={loading}
      error={error}
      onRetry={onRetry}
      empty={<EmptyState title={t('За этот период продаж нет')} />}
    />
  )
}

function DiscountsCard({ data, common }) {
  const discounts = data?.discounts
  const reasons = (discounts?.reasons || []).map(r => ({ key: r.key, label: r.label, value: r.amount }))
  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader title={t('Влияние скидок')} description={t('Насколько скидки снизили средний чек')} />
        {!discounts ? <Skeleton className="h-32" /> : (
          <dl className="space-y-3 text-[13px]">
            <Row label={t('Средний чек без скидок')} value={formatValue(discounts.list_average, 'money')} />
            <Row label={t('Средний чек со скидками')} value={formatValue(discounts.average, 'money')} />
            <Row
              label={t('Скидки снизили чек на')}
              value={discounts.effect == null ? '—' : `${formatValue(discounts.effect, 'money')} · ${formatValue(discounts.effect_percent, 'percent')}`}
              strong
            />
            <Row label={t('Раздано скидками')} value={formatValue(discounts.total, 'money')} />
            <Row
              label={t('Абонементов со скидкой')}
              value={`${formatValue(discounts.count, 'count')} · ${formatValue(discounts.share_of_sales, 'percent')}`}
            />
          </dl>
        )}
      </Card>
      <ChartCard autoHeight className="lg:col-span-2" title={t('Скидки по причинам')} description={t('Сколько центр раздал скидками и почему')} {...common} empty={!reasons.length}>
        <RankBars items={reasons} unit="money" color={PALETTE[3]} />
      </ChartCard>
    </div>
  )
}

function Row({ label, value, strong }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd className={strong ? 'font-bold text-ink' : 'font-semibold text-ink'}>{value}</dd>
    </div>
  )
}

function DebtSection({ debt }) {
  const data = debt.data
  if (debt.error && !data) return <Card><ErrorState onRetry={debt.reload} /></Card>
  const end = data?.end
  const repaid = data?.repaid
  const total = end && tile(end.total, 'money', { previous: data.previous.total, kind: 'snapshot' })
  const share = end && tile(end.debtors_share, 'percent', { kind: 'snapshot' })
  const repaidTile = repaid && tile(repaid.percent, 'percent')
  const over60 = end && tile(end.by_age?.over_60, 'money', { kind: 'snapshot' })
  const ages = AGE_KEYS.map(key => ({ key, value: end?.by_age?.[key] || 0 }))
  const monthly = (data?.monthly || []).filter(m => m.by_age).flatMap(m => AGE_KEYS.map(key => ({
    month: m.month, key, value: Number(m.by_age[key] || 0),
  })))
  const monthsWithData = (data?.monthly || []).filter(m => m.total != null).length
  const common = { loading: debt.loading, error: debt.error, onRetry: debt.reload, metric: data ? tile(end.total, 'money') : null }

  return (
    <section>
      <h2 className="mb-3 text-lg font-bold text-ink">{t('Задолженность')}</h2>
      <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricTile name="debt_end" metric={total} loading={debt.loading} />
        <MetricTile name="debt_age_over_60" metric={over60} loading={debt.loading} />
        <MetricTile name="debtors_share" metric={share} loading={debt.loading} />
        <MetricTile name="debt_repaid" metric={repaidTile} loading={debt.loading} />
      </div>

      <p className="mb-4 flex items-start gap-2 rounded-lg border border-info-50 bg-info-50/40 px-4 py-3 text-[13px] text-ink-muted">
        <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
        {t('Долг — тот же расчёт, что экран «Задолженности». За прошлые даты — сохранённые ежедневно цифры: задним числом долг не пересчитывается.')}
        {data?.history_since && ` ${t('История копится с {date}.', { date: formatDate(data.history_since) })}`}
      </p>
      {end && end.total == null && (
        <Card className="mb-4">
          <EmptyState title={t('На конец периода данных нет')} description={t('Цифры долга сохраняются каждый день с момента обновления системы. Выберите период, который заканчивается позже.')} />
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard className="lg:col-span-2" title={t('Долг на конец месяца')} description={t('Растёт или сокращается, по давности')} height={280} {...common} empty={!monthly.length}>
          {monthsWithData < 2
            ? <EmptyState title={t('История только начала копиться')} description={t('График появится, когда накопится хотя бы два месяца.')} className="py-6" />
            : <StackedBars rows={monthly} unit="money" />}
        </ChartCard>
        <ChartCard autoHeight title={t('Структура по давности')} description={t('На конец периода, от даты начала абонемента')} {...common} empty={!end?.by_age || !Number(end.total)}>
          <DonutChart items={ages} unit="money" colors={AGE_COLORS} centerLabel={t('долг')} />
        </ChartCard>
      </div>

      <Card className="mt-4">
        <CardHeader title={t('Погашение долгов')} description={t('Долг по абонементам, проданным до начала периода, и сколько из него оплатили за период')} />
        {!repaid ? <Skeleton className="h-16" /> : !Number(repaid.owed_at_start) ? (
          <p className="text-[13px] text-ink-muted">{t('На начало периода долгов не было.')}</p>
        ) : (
          <>
            <p className="text-[13px] text-ink">
              {t('На начало периода долг {owed}, погашено {repaid}, осталось {left}.', {
                owed: formatValue(repaid.owed_at_start, 'money'),
                repaid: formatValue(repaid.repaid, 'money'),
                left: formatValue(repaid.remaining, 'money'),
              })}
            </p>
            <div className="mt-3 h-3 overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full bg-success-600" style={{ width: `${Number(repaid.percent || 0)}%` }} />
            </div>
          </>
        )}
      </Card>
    </section>
  )
}
