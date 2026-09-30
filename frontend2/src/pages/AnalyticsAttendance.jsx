import { Card, ErrorState, PageHeader } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ChartCard, ComboChart, DonutChart, HeatmapChart, MetricTile, PALETTE, RankBars,
  useAnalyticsCatalog, useAnalyticsFilters, useBreakdown, useHeatmap, useMetrics,
} from '../components/analytics'

const TILES = ['visits', 'attendance_rate', 'absences', 'active_children']
const METRICS = [...TILES, 'attendance_marks']
const REASON_COLORS = ['var(--color-danger-600)', PALETTE[1], 'var(--color-warning-600)', 'var(--color-ink-subtle)']

/**
 * «Был» / все отметки по одному измерению: доля посещений по группам и
 * преподавателям. Сортировка — с худших: смотреть надо туда, где падает.
 */
function rates(visited, marked, minMarks = 10) {
  if (!visited?.items || !marked?.items) return null
  const seen = Object.fromEntries(visited.items.map(item => [item.key, Number(item.value)]))
  return marked.items
    .filter(item => Number(item.value) >= minMarks)
    .map(item => ({ ...item, value: Math.round(((seen[item.key] || 0) / Number(item.value)) * 1000) / 10 }))
    .sort((a, b) => a.value - b.value)
}

/**
 * Отчёт «Посещаемость» (TRU-121 на каркасе TRU-113): тренд, причины
 * пропусков, группы и преподаватели с самой низкой долей посещений,
 * загрузка по дням и часам.
 */
export default function AnalyticsAttendance() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const { data, loading, error, reload } = useMetrics(METRICS, filters)
  const metrics = data?.metrics || {}
  const common = { loading, error, onRetry: reload, metric: metrics.visits }

  const reasons = useBreakdown('absences', 'reason', filters)
  const groupVisits = useBreakdown('visits', 'group', filters)
  const groupMarks = useBreakdown('attendance_marks', 'group', filters)
  const teacherVisits = useBreakdown('visits', 'teacher', filters)
  const teacherMarks = useBreakdown('attendance_marks', 'teacher', filters)
  const heatmap = useHeatmap(filters)

  const groupRates = rates(groupVisits.data, groupMarks.data)
  const teacherRates = rates(teacherVisits.data, teacherMarks.data)?.filter(item => item.key)

  return (
    <>
      <PageHeader title={t('Аналитика')} description={t('Посещаемость и пропуски')} />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} previous={data?.previous_period} />

      {error && !data ? (
        <Card><ErrorState onRetry={reload} /></Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            {TILES.map(name => <MetricTile key={name} name={name} metric={metrics[name]} loading={loading} />)}
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <ChartCard className="lg:col-span-2" title={t('Посещения и доля посещений')} description={t('Тренд важнее одного числа: падает ли доля «был»')} {...common}>
              <ComboChart
                bars={metrics.visits?.series}
                line={metrics.attendance_rate?.series}
                granularity={data?.period?.granularity}
                barLabel={t('Посещений')}
                lineLabel={t('Доля посещений')}
              />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('Почему пропускают')}
              description={t('Причины из отметки «не был»')}
              ready={Boolean(reasons.data)}
              empty={!reasons.data?.items.length}
              {...common}
              metric={metrics.absences}
            >
              <DonutChart items={reasons.data?.items} unit="count" colors={REASON_COLORS} centerLabel={t('пропусков')} />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('Группы с низкой посещаемостью')}
              description={t('Доля «был» от всех отметок, с худших')}
              ready={Boolean(groupRates)}
              empty={!groupRates?.length}
              {...common}
            >
              <RankBars items={groupRates} unit="percent" showShare={false} max={100} color="var(--color-warning-600)" limit={6} />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('По преподавателям')}
              description={t('Доля «был» на их занятиях, с худших')}
              ready={Boolean(teacherRates)}
              empty={!teacherRates?.length}
              {...common}
            >
              <RankBars items={teacherRates} unit="percent" showShare={false} max={100} color={PALETTE[1]} limit={6} />
            </ChartCard>
            <ChartCard
              autoHeight
              title={t('Когда ходят дети')}
              description={t('Посещения по дню недели и часу')}
              height={220}
              ready={Boolean(heatmap.data)}
              empty={!heatmap.data?.cells.length}
              {...common}
            >
              <HeatmapChart cells={heatmap.data?.cells || []} />
            </ChartCard>
          </div>
        </>
      )}
    </>
  )
}
