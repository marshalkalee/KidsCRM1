import { Card, CardHeader, DataTable, PageHeader } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsToolbar, BarsChart, ChartCard, Change, ComboChart, DonutChart, FunnelChart, GaugeChart,
  HeatmapChart, MetricTile, PALETTE, RankBars, TrendChart,
  formatValue, useAnalyticsCatalog, useAnalyticsFilters,
} from '../components/analytics'

/**
 * Примеры компонентов отчётов (TRU-113) — для тех, кто собирает отчёты
 * M3: все состояния на выдуманных числах. В меню не выводится, адрес —
 * /analytics/kit. Данные — ровно в той форме, что отдаёт API.
 */
const DAYS = Array.from({ length: 30 }, (_, i) => `2026-09-${String(i + 1).padStart(2, '0')}`)
const wave = (base, amp) => DAYS.map((date, i) => ({ date, value: Math.round(base + amp * Math.sin(i / 3) + (i % 7 === 6 ? -base * 0.6 : 0)) }))

const SAMPLE = {
  revenue: { unit: 'money', kind: 'event', value: '2392000', previous: '2105000', change_percent: '13.6', enough_data: true, series: wave(80000, 25000) },
  debt_total: { unit: 'money', kind: 'snapshot', value: '442000', previous: '380000', change_percent: '16.3', enough_data: true, series: wave(420000, 20000) },
  visits: { unit: 'count', kind: 'event', value: 761, previous: 812, change_percent: '-6.3', enough_data: true, series: wave(26, 8) },
  attendance_rate: { unit: 'percent', kind: 'ratio', value: '87.4', previous: '87.4', change_percent: '0', enough_data: true, series: wave(87, 4) },
  new_leads: { unit: 'count', kind: 'event', value: 12, previous: 0, change_percent: null, enough_data: false, data_since: '2026-09-20', days_until_enough: 18, series: wave(1, 1) },
  group_fill: { unit: 'percent', kind: 'snapshot', value: '54.2', previous: null, change_percent: null, enough_data: true, series: [{ date: '2026-09-30', value: '54.2' }] },
  empty: { unit: 'count', kind: 'event', value: 0, previous: 0, change_percent: null, enough_data: true, data_since: '2026-01-01', series: DAYS.map(date => ({ date, value: 0 })) },
  none: { unit: 'count', kind: 'event', value: 0, enough_data: false, data_since: null, days_until_enough: 28, series: [] },
}

const METHODS = [
  { key: 'kaspi_transfer', value: '1450000' },
  { key: 'cash', value: '610000' },
  { key: 'card', value: '332000' },
]
const SOURCES = [
  { key: '1', label: 'Instagram', value: 41 },
  { key: '2', label: 'Сарафанное радио', value: 23 },
  { key: '3', label: '2ГИС', value: 12 },
  { key: null, label: null, value: 4 },
]
const HEAT = [1, 2, 3, 4, 5, 6].flatMap(weekday => [10, 15, 16, 17, 18, 19].map(hour => ({
  weekday, hour, value: weekday === 6 && hour > 16 ? 0 : Math.round(20 + 60 * Math.sin((hour - 9) / 3) * (weekday % 3 ? 1 : 0.6)),
})))

const BRANCH_ROWS = [
  { name: 'Абая', revenue: 1240000, visits: 402, change: '8.2' },
  { name: 'Саина', revenue: 830000, visits: 251, change: '-4.5' },
  { name: 'Мега', revenue: 322000, visits: 108, change: '0' },
]

export default function AnalyticsKit() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  return (
    <>
      <PageHeader title={t('Компоненты отчётов')} description={t('Как выглядят плитки, графики и их состояния — на выдуманных числах')} />

      <Section title={t('Панель периода и филиалов')} note="AnalyticsToolbar · useAnalyticsFilters">
        <AnalyticsToolbar filters={filters} catalog={catalog} period={{ start: '2026-09-01', end: '2026-09-30' }} previous={{ start: '2026-08-01', end: '2026-08-30' }} />
      </Section>

      <Section title={t('Плитки')} note="MetricTile">
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <MetricTile name="revenue" metric={SAMPLE.revenue} />
          <MetricTile name="debt_total" metric={SAMPLE.debt_total} />
          <MetricTile name="visits" metric={SAMPLE.visits} />
          <MetricTile name="attendance_rate" metric={SAMPLE.attendance_rate} />
          <MetricTile name="new_leads" metric={SAMPLE.new_leads} />
          <MetricTile name="group_fill" metric={SAMPLE.group_fill} />
          <MetricTile name="active_children" metric={SAMPLE.none} />
          <MetricTile name="payments_count" />
        </div>
      </Section>

      <Section title={t('Графики')} note="ChartCard · TrendChart · BarsChart">
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard title={t('Линия с прошлым периодом')} description="TrendChart previous" metric={SAMPLE.revenue}>
            <TrendChart series={SAMPLE.revenue.series} previous={wave(70000, 20000)} unit="money" granularity="day" />
          </ChartCard>
          <ChartCard title={t('Столбцы')} description="BarsChart" metric={SAMPLE.visits}>
            <BarsChart series={SAMPLE.visits.series} unit="count" granularity="day" color={PALETTE[1]} />
          </ChartCard>
          <ChartCard title={t('Столбцы и линия')} description="ComboChart" metric={SAMPLE.visits}>
            <ComboChart bars={SAMPLE.visits.series} line={SAMPLE.attendance_rate.series} granularity="day" barLabel={t('Посещений')} lineLabel={t('Доля посещений')} />
          </ChartCard>
          <ChartCard
              autoHeight title={t('Кольцо')} description="DonutChart" metric={SAMPLE.revenue} empty={false}>
            <DonutChart items={METHODS} unit="money" centerLabel={t('за период')} />
          </ChartCard>
          <ChartCard
              autoHeight title={t('Тепловая карта')} description="HeatmapChart" metric={SAMPLE.visits} empty={false} height={220}>
            <HeatmapChart cells={HEAT} />
          </ChartCard>
          <ChartCard
              autoHeight title={t('Шкала')} description="GaugeChart" metric={SAMPLE.group_fill} empty={false} height={220}>
            <div className="flex h-full items-center justify-center gap-6">
              <GaugeChart value={72} threshold={50} label="72" />
              <GaugeChart value={38} threshold={50} label="38" />
            </div>
          </ChartCard>
          <ChartCard
              autoHeight title={t('Рейтинг')} description="RankBars" metric={SAMPLE.new_leads} empty={false}>
            <RankBars items={SOURCES} unit="count" color={PALETTE[3]} />
          </ChartCard>
          <ChartCard title={t('Загрузка')} description="metric = undefined" />
          <ChartCard title={t('Ошибка')} description="error" error onRetry={() => {}} />
          <ChartCard title={t('Данных пока мало')} description="enough_data = false" metric={SAMPLE.new_leads} />
          <ChartCard title={t('За период пусто')} description={t('все точки — 0')} metric={SAMPLE.empty} />
          <ChartCard title={t('История снимка')} description={t('одна точка')} metric={SAMPLE.group_fill} />
          <ChartCard title={t('Данных ещё нет')} description="data_since = null" metric={SAMPLE.none} />
        </div>
      </Section>

      <Section title={t('Таблица')} note="DataTable · formatValue · Change">
        <DataTable
          columns={[
            { key: 'name', header: t('Филиал'), primary: true },
            { key: 'revenue', header: t('Выручка'), align: 'right', render: row => formatValue(row.revenue, 'money') },
            { key: 'visits', header: t('Посещений'), align: 'right', render: row => formatValue(row.visits, 'count') },
            { key: 'change', header: t('К прошлому периоду'), mobileAside: true, render: row => <Change metric={{ change_percent: row.change }} compact /> },
          ]}
          rows={BRANCH_ROWS}
          rowKey={row => row.name}
        />
      </Section>

      <Section title={t('Воронка')} note="FunnelChart">
        <Card className="max-w-2xl">
          <FunnelChart stages={[
            { label: t('Новая'), value: 120 },
            { label: t('Связались'), value: 96 },
            { label: t('Записан на пробное'), value: 61 },
            { label: t('Пришёл на пробное'), value: 48 },
            { label: t('Купил абонемент'), value: 29 },
          ]} />
        </Card>
      </Section>
    </>
  )
}

function Section({ title, note, children }) {
  return (
    <section className="mb-8">
      <CardHeader title={title} description={<code className="text-[12px]">{note}</code>} />
      {children}
    </section>
  )
}
