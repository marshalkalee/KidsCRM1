import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Button, Card, ErrorState, PageHeader } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ExportButton, BarsChart, ChartCard, ComboChart, DonutChart, GaugeChart, HeatmapChart,
  MetricTile, OwnerTiles, PALETTE, RankBars, TrendChart,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet, useBreakdown, useHeatmap, useMetrics,
} from '../components/analytics'

const TILES = [
  'revenue', 'average_check', 'debt_total', 'new_leads',
  'visits', 'attendance_rate', 'active_children', 'group_fill',
]
const METRICS = [...new Set([...TILES, 'payments_count'])]
// Кольцо посещаемости: зелёный — был, синий — отработка, оранжевый — не был.
const ATTENDANCE_COLORS = ['var(--color-success-600)', PALETTE[1], 'var(--color-warning-600)']
const STATUS_ORDER = ['present', 'makeup', 'absent']

/**
 * «Аналитика», главный экран дашборда владельца (TRU-129, ТЗ раздел 7):
 * семь цифр верхнего уровня — выручка, задолженность, заполняемость,
 * конверсия заявок и продлений, зона ухода, прогноз. Каждая плитка —
 * ссылка в подробный отчёт; листать не нужно. Графики каркаса (TRU-113)
 * — на один клик глубже, кнопкой «Графики»: пока свёрнуты, не грузятся.
 */
export default function Analytics() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const { data, loading, error, reload } = useAnalyticsGet('dashboard', '', filters)
  const [charts, setCharts] = useState(false)
  const branchNote = data && !data.all_branches ? data.branches.map(b => b.name).join(', ') : t('Все филиалы')

  return (
    <>
      <PageHeader title={t('Аналитика')} description={branchNote} actions={<ExportButton report="overview" filters={filters} />} />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} previous={data?.previous_period} />

      {error && !data ? (
        <Card className="mb-5"><ErrorState onRetry={reload} /></Card>
      ) : (
        <OwnerTiles data={data} loading={loading} />
      )}

      <Button
        variant="secondary"
        icon={charts ? ChevronUp : ChevronDown}
        className="mb-5"
        aria-expanded={charts}
        onClick={() => setCharts(open => !open)}
      >
        {charts ? t('Скрыть графики') : t('Графики')}
      </Button>
      {charts && <OverviewCharts filters={filters} catalog={catalog} />}
    </>
  )
}

/** Графики каркаса (TRU-113): динамика, структура, «когда ходят». */
function OverviewCharts({ filters, catalog }) {
  const { data, loading, error, reload } = useMetrics(METRICS, filters)
  const metrics = data?.metrics || {}
  const granularity = data?.period?.granularity
  const manyBranches = data && (data.all_branches ? (catalog?.branches?.length || 0) > 1 : data.branches.length > 1)

  const methods = useBreakdown('revenue', 'method', filters)
  const statuses = useBreakdown('attendance_marks', 'status', filters)
  const revenueRank = useBreakdown('revenue', manyBranches ? 'branch' : 'direction', filters)
  const sources = useBreakdown('new_leads', 'source', filters)
  const heatmap = useHeatmap(filters)

  const statusItems = statuses.data
    ? [...statuses.data.items].sort((a, b) => STATUS_ORDER.indexOf(a.key) - STATUS_ORDER.indexOf(b.key))
    : null
  const common = { loading, error, onRetry: reload }

  return (
    <>
      {error && !data ? (
        <Card><ErrorState onRetry={reload} /></Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            {TILES.map(name => <MetricTile key={name} name={name} metric={metrics[name]} loading={loading} />)}
          </div>

          <Section title={t('Деньги')}>
            <ChartCard
              className="lg:col-span-2"
              title={t('Выручка')}
              description={t('Подтверждённые оплаты · пунктир — прошлый период')}
              metric={metrics.revenue}
              {...common}
            >
              <TrendChart series={metrics.revenue?.series} previous={metrics.revenue?.previous_series} unit="money" granularity={granularity} label={t('Выручка')} />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('Как платят')}
              description={t('Доля выручки по способам оплаты')}
              metric={metrics.revenue}
              ready={Boolean(methods.data)}
              empty={!methods.data?.items.length}
              {...common}
            >
              <DonutChart items={methods.data?.items} unit="money" centerLabel={t('за период')} />
            </ChartCard>
          </Section>

          <Section title={t('Посещаемость')}>
            <ChartCard
              className="lg:col-span-2"
              title={t('Посещения и доля посещений')}
              description={t('Столбцы — сколько раз пришли, линия — какая доля отметок «был»')}
              metric={metrics.visits}
              {...common}
            >
              <ComboChart
                bars={metrics.visits?.series}
                line={metrics.attendance_rate?.series}
                granularity={granularity}
                barLabel={t('Посещений')}
                lineLabel={t('Доля посещений')}
              />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('Из чего складываются отметки')}
              description={t('Был, отработка, не был')}
              metric={metrics.attendance_marks || metrics.visits}
              ready={Boolean(statuses.data)}
              empty={!statusItems?.length}
              {...common}
            >
              <DonutChart items={statusItems} unit="count" colors={ATTENDANCE_COLORS} centerLabel={t('отметок')} />
            </ChartCard>
            <ChartCard
              autoHeight
              className="lg:col-span-2"
              title={t('Когда ходят дети')}
              description={t('Посещения по дню недели и часу начала занятия')}
              metric={metrics.visits}
              height={220}
              ready={Boolean(heatmap.data)}
              empty={!heatmap.data?.cells.length}
              {...common}
            >
              <HeatmapChart cells={heatmap.data?.cells || []} />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('Заполняемость групп')}
              description={t('Дети в группах от вместимости, сейчас')}
              metric={metrics.group_fill}
              height={220}
              empty={metrics.group_fill?.value == null}
              {...common}
            >
              <div className="flex h-full items-center justify-center">
                <GaugeChart value={metrics.group_fill?.value} threshold={catalog?.group_underfilled_percent} label={t('Заполняемость групп')} />
              </div>
            </ChartCard>
          </Section>

          <Section title={t('Продажи и долги')}>
            <ChartCard
              autoHeight
              title={manyBranches ? t('Выручка по филиалам') : t('Выручка по направлениям')}
              description={t('Кто приносит больше')}
              metric={metrics.revenue}
              ready={Boolean(revenueRank.data)}
              empty={!revenueRank.data?.items.length}
              {...common}
            >
              <RankBars items={revenueRank.data?.items} unit="money" />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('Откуда заявки')}
              description={t('Новые заявки по источникам')}
              metric={metrics.new_leads}
              ready={Boolean(sources.data)}
              empty={!sources.data?.items.length}
              {...common}
            >
              <RankBars items={sources.data?.items} unit="count" color={PALETTE[3]} />
            </ChartCard>
            <ChartCard title={t('Новые заявки')} description={t('Без продлений')} metric={metrics.new_leads} {...common}>
              <BarsChart series={metrics.new_leads?.series} unit="count" granularity={granularity} color={PALETTE[3]} label={t('Новых заявок')} />
            </ChartCard>
            <ChartCard
              className="lg:col-span-3"
              title={t('Задолженность')}
              description={t('На конец каждого дня')}
              metric={metrics.debt_total}
              height={200}
              {...common}
            >
              <TrendChart series={metrics.debt_total?.series} unit="money" granularity="day" color="var(--color-warning-600)" label={t('Задолженность')} />
            </ChartCard>
          </Section>
        </>
      )}
    </>
  )
}

function Section({ title, children }) {
  return (
    <section className="mb-6">
      <h2 className="mb-3 text-[13px] font-bold uppercase tracking-[0.06em] text-ink-subtle">{title}</h2>
      <div className="grid gap-4 lg:grid-cols-3">{children}</div>
    </section>
  )
}
