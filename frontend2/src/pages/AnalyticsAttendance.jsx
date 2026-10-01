import { Link } from 'react-router-dom'
import { CalendarCheck, CheckCheck, Percent, TrendingDown, TrendingUp, UserRound, XCircle } from 'lucide-react'
import {
  AnalyticsNav, AnalyticsToolbar, ComboChart, DonutChart, ExportButton, PALETTE, RankBars,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'
import { Badge, Card, CardHeader, DataTable, ErrorState, PageHeader, Skeleton, cn } from '../ui'
import { t } from '../i18n'

const REASON_COLORS = ['var(--color-danger-600)', PALETTE[1], 'var(--color-warning-600)', 'var(--color-ink-subtle)']
const BREAKDOWNS = [
  ['group', 'По группам'],
  ['direction', 'По направлениям'],
  ['branch', 'По филиалам'],
  ['teacher', 'По преподавателям'],
  ['weekday', 'По дням недели'],
]

export default function AnalyticsAttendance() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const report = useAnalyticsGet('attendance-trends', '', filters)
  const data = report.data

  return (
    <>
      <PageHeader
        title={t('Посещаемость и пропуски')}
        description={t('Динамика посещаемости, причины пропусков и отклонение от личной нормы ребёнка')}
        actions={<ExportButton report="attendance" filters={filters} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      {report.error && !data ? (
        <Card><ErrorState onRetry={report.reload} /></Card>
      ) : !data ? (
        <LoadingState />
      ) : (
        <div className={cn(report.loading && 'opacity-60 transition-opacity')}>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <SummaryCard icon={CalendarCheck} label={t('Проведено занятий')} value={data.summary.lessons_held} />
            <SummaryCard icon={CheckCheck} label={t('Посещено')} value={data.summary.attended} />
            <SummaryCard icon={Percent} label={t('Посещаемость')} value={formatPercent(data.summary.attendance_rate)} />
            <SummaryCard icon={XCircle} label={t('Пропущено')} value={data.summary.absences} warning={data.summary.absences > 0} />
          </div>

          <div className="mb-5 grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader
                title={t('Динамика по неделям')}
                description={t('Посещения и доля посещений по неделям')}
              />
              {data.weekly.some(row => row.marked) ? (
                <div className="h-72">
                  <ComboChart
                    bars={data.weekly.map(row => ({ date: row.date, value: row.attended }))}
                    line={data.weekly.map(row => ({ date: row.date, value: row.value }))}
                    granularity="week"
                    barLabel={t('Посещений')}
                    lineLabel={t('Доля посещений')}
                  />
                </div>
              ) : <EmptyText />}
            </Card>
            <Card>
              <CardHeader title={t('Почему пропускают')} description={t('Распределение причин пропусков')} />
              {data.absence_reasons.length ? (
                <DonutChart
                  items={data.absence_reasons.map(row => ({ ...row, label: t(row.label || 'Не указано') }))}
                  unit="count"
                  colors={REASON_COLORS}
                  centerLabel={t('пропусков')}
                />
              ) : <EmptyText />}
            </Card>
          </div>

          <section className="mb-6">
            <div className="mb-3">
              <h2 className="text-lg font-bold text-ink">{t('Разрезы посещаемости')}</h2>
              <p className="text-sm text-ink-muted">{t('Доля посещений по группе, направлению, филиалу, преподавателю и дню недели')}</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {BREAKDOWNS.map(([key, title]) => (
                <BreakdownCard
                  key={key}
                  title={t(title)}
                  rows={key === 'weekday'
                    ? data.breakdowns[key].map(row => ({ ...row, label: t(row.label) }))
                    : data.breakdowns[key]}
                />
              ))}
            </div>
          </section>

          <section>
            <div className="mb-3">
              <h2 className="text-lg font-bold text-ink">{t('Посещаемость по ребёнку')}</h2>
              <p className="text-sm text-ink-muted">
                {t('Сравнение текущих пропусков с личной нормой ребёнка.')}
              </p>
            </div>
            <Card className="mb-3 flex items-start gap-3 bg-info-50/50">
              <UserRound className="mt-0.5 size-5 shrink-0 text-info-600" />
              <p className="text-[13px] text-ink-muted">
                {t('Личная норма — доля пропусков за предыдущие {days} дней. Для сравнения нужно не меньше {marks} отметок.', {
                  days: data.baseline.days,
                  marks: data.baseline.minimum_marks,
                })}
                {' '}{t('Это база для риск-листа, а не оценка ребёнка.')}
              </p>
            </Card>
            <ChildrenTable rows={data.children} />
          </section>
        </div>
      )}
    </>
  )
}

function LoadingState() {
  return (
    <>
      <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
        {[1, 2, 3, 4].map(item => <Skeleton key={item} className="h-32" />)}
      </div>
      <Skeleton className="h-96" />
    </>
  )
}

function SummaryCard({ icon: Icon, label, value, warning = false }) {
  return (
    <Card className="min-w-0">
      <div className={cn('mb-3 flex size-9 items-center justify-center rounded-md', warning ? 'bg-warning-50 text-warning-600' : 'bg-brand-50 text-brand-600')}>
        <Icon className="size-4.5" />
      </div>
      <p className="text-xl font-bold text-ink">{value ?? '—'}</p>
      <p className="mt-1 text-xs text-ink-muted">{label}</p>
    </Card>
  )
}

function BreakdownCard({ title, rows }) {
  const items = (rows || []).filter(row => row.label && row.value != null)
  return (
    <Card>
      <CardHeader title={title} />
      {items.length
        ? <RankBars items={items} unit="percent" max={100} showShare={false} limit={10} />
        : <EmptyText />}
    </Card>
  )
}

function ChildrenTable({ rows }) {
  const columns = [
    {
      key: 'name',
      header: t('Ребёнок'),
      primary: true,
      render: row => <Link to={`/children/${row.id}`} className="font-semibold text-ink hover:text-brand-600">{row.name}</Link>,
    },
    {
      key: 'attended',
      header: t('Посещено / отмечено'),
      align: 'right',
      render: row => `${row.attended} / ${row.marked}`,
    },
    { key: 'absences', header: t('Пропущено'), align: 'right' },
    { key: 'absence_rate', header: t('Текущие пропуски'), align: 'right', render: row => formatPercent(row.absence_rate) },
    {
      key: 'baseline',
      header: t('Личная норма'),
      align: 'right',
      render: row => row.has_baseline ? formatPercent(row.baseline.absence_rate) : t('Недостаточно истории'),
    },
    {
      key: 'trend',
      header: t('Изменение'),
      mobileAside: true,
      render: row => <TrendBadge row={row} />,
    },
  ]
  return <DataTable columns={columns} rows={rows} />
}

function TrendBadge({ row }) {
  if (!row.has_baseline) return <Badge>{t('Недостаточно истории')}</Badge>
  if (row.trend === 'rising') {
    return (
      <span title={t('пропуски участились')}>
        <Badge tone="danger"><TrendingUp className="size-3.5" />+{row.absence_change_pp} {t('п.п.')}<span className="sr-only">{t('пропуски участились')}</span></Badge>
      </span>
    )
  }
  if (row.trend === 'falling') {
    return (
      <span title={t('пропусков стало меньше')}>
        <Badge tone="success"><TrendingDown className="size-3.5" />{row.absence_change_pp} {t('п.п.')}<span className="sr-only">{t('пропусков стало меньше')}</span></Badge>
      </span>
    )
  }
  return (
    <span title={t('без заметного изменения')}>
      <Badge>{row.absence_change_pp > 0 ? '+' : ''}{row.absence_change_pp} {t('п.п.')}<span className="sr-only">{t('без заметного изменения')}</span></Badge>
    </span>
  )
}

function EmptyText() {
  return <p className="py-8 text-center text-sm text-ink-muted">{t('Нет данных')}</p>
}

function formatPercent(value) {
  return value == null ? '—' : `${value}%`
}
