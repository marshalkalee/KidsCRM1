import { Card, ErrorState, PageHeader } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsToolbar, BarsChart, ChartCard, MetricTile, PALETTE, TrendChart,
  useAnalyticsCatalog, useAnalyticsFilters, useMetrics,
} from '../components/analytics'

const TILES = [
  'revenue', 'average_check', 'debt_total', 'new_leads',
  'visits', 'attendance_rate', 'active_children', 'group_fill',
]
const METRICS = [...new Set([...TILES, 'payments_count'])]

/**
 * «Аналитика» (TRU-113): каркас отчётов владельца — период и филиалы,
 * плитки с динамикой, графики. Главный экран дашборда соберут в TRU-129,
 * отчёты M3 добавят свои метрики и карточки на этот же каркас.
 */
export default function Analytics() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const { data, loading, error, reload } = useMetrics(METRICS, filters)
  const metrics = data?.metrics || {}
  const granularity = data?.period?.granularity
  const branchNote = data && !data.all_branches ? data.branches.map(b => b.name).join(', ') : t('Все филиалы')

  return (
    <>
      <PageHeader title={t('Аналитика')} description={branchNote} />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} previous={data?.previous_period} />

      {error && !data ? (
        <Card><ErrorState onRetry={reload} /></Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            {TILES.map(name => <MetricTile key={name} name={name} metric={metrics[name]} loading={loading} />)}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title={t('Выручка')} description={t('Подтверждённые оплаты')} metric={metrics.revenue} loading={loading} error={error} onRetry={reload}>
              <TrendChart series={metrics.revenue?.series} unit="money" granularity={granularity} />
            </ChartCard>
            <ChartCard title={t('Посещения')} description={t('«Был» и отработки')} metric={metrics.visits} loading={loading} error={error} onRetry={reload}>
              <BarsChart series={metrics.visits?.series} unit="count" granularity={granularity} color={PALETTE[1]} />
            </ChartCard>
            <ChartCard title={t('Доля посещений')} description={t('Сколько отметок — «был»')} metric={metrics.attendance_rate} loading={loading} error={error} onRetry={reload}>
              <TrendChart series={metrics.attendance_rate?.series} unit="percent" granularity={granularity} color={PALETTE[2]} />
            </ChartCard>
            <ChartCard title={t('Новые заявки')} description={t('Без продлений')} metric={metrics.new_leads} loading={loading} error={error} onRetry={reload}>
              <BarsChart series={metrics.new_leads?.series} unit="count" granularity={granularity} color={PALETTE[3]} />
            </ChartCard>
            <ChartCard title={t('Задолженность')} description={t('На конец каждого дня')} metric={metrics.debt_total} loading={loading} error={error} onRetry={reload}>
              <TrendChart series={metrics.debt_total?.series} unit="money" granularity="day" color={PALETTE[3]} />
            </ChartCard>
            <ChartCard title={t('Заполняемость групп')} description={t('На конец каждого дня')} metric={metrics.group_fill} loading={loading} error={error} onRetry={reload}>
              <TrendChart series={metrics.group_fill?.series} unit="percent" granularity="day" color={PALETTE[1]} />
            </ChartCard>
          </div>
        </>
      )}
    </>
  )
}
