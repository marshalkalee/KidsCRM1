import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CalendarCheck, CalendarX, Info, Presentation, UserRoundCheck, UsersRound } from 'lucide-react'
import {
  AnalyticsNav, AnalyticsToolbar, ExportButton, RankBars, StackedBars, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'
import { Badge, Card, CardHeader, DataTable, ErrorState, PageHeader, Select, Skeleton, cn } from '../ui'
import { t } from '../i18n'

const FILTER_KEYS = ['direction', 'teacher']

export default function AnalyticsTeachers() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const [params, setParams] = useSearchParams()
  const extra = useMemo(() => {
    const query = new URLSearchParams()
    FILTER_KEYS.forEach(key => {
      const value = params.get(key)
      if (value) query.set(key, value)
    })
    return query.toString()
  }, [params])
  const report = useAnalyticsGet('teacher-workload', extra, filters)
  const data = report.data

  function setFilter(key, value) {
    setParams(current => {
      const next = new URLSearchParams(current)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace: true })
  }

  const monthly = (data?.teachers || []).flatMap(teacher => teacher.trend.map(point => ({
    month: point.date,
    key: teacher.id,
    label: teacher.name,
    value: point.planned,
  })))
  const loadRanking = (data?.teachers || []).map(teacher => ({
    key: teacher.id,
    label: teacher.name,
    value: teacher.lessons_per_week,
  }))

  return (
    <>
      <PageHeader
        title={t('Загрузка преподавателей')}
        description={t('Объём нагрузки по расписанию — не оценка качества работы')}
        actions={<ExportButton report="teacher_workload" filters={filters} extra={extra} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      <Card className="mb-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_2fr] lg:items-end">
          <ReportSelect
            label={t('Направление')}
            value={params.get('direction') || ''}
            onChange={value => setFilter('direction', value)}
            options={data?.filters?.directions}
            all={t('Все направления')}
          />
          <ReportSelect
            label={t('Преподаватель')}
            value={params.get('teacher') || ''}
            onChange={value => setFilter('teacher', value)}
            options={data?.filters?.teachers}
            all={t('Все преподаватели')}
          />
          <p className="flex items-start gap-2 rounded-md bg-info-50 p-3 text-[13px] text-ink-muted">
            <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
            {t('Отчёт показывает загрузку, а не эффективность. Число учеников зависит от направления, времени занятий и возраста группы.')}
          </p>
        </div>
      </Card>

      {report.error && !data ? (
        <Card><ErrorState onRetry={report.reload} /></Card>
      ) : !data ? (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-6">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-28" />)}</div>
      ) : (
        <div className={cn(report.loading && 'opacity-60 transition-opacity')}>
          <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <SummaryCard icon={Presentation} label={t('Преподавателей')} value={data.summary.teachers} />
            <SummaryCard icon={CalendarCheck} label={t('Запланировано')} value={data.summary.planned} />
            <SummaryCard icon={UserRoundCheck} label={t('Проведено')} value={data.summary.completed} />
            <SummaryCard icon={CalendarX} label={t('Отменено')} value={data.summary.cancelled} warning={data.summary.cancelled > 0} />
            <SummaryCard icon={CalendarX} label={t('По причине преподавателя')} value={data.summary.teacher_cancelled} warning={data.summary.teacher_cancelled > 0} />
            <SummaryCard icon={UsersRound} label={t('Уникальных учеников')} value={data.summary.students} />
          </div>

          {data.teachers.length ? (
            <>
              <div className="mb-5 grid gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader title={t('Сравнение нагрузки')} description={t('Среднее количество занятий в неделю за выбранный период.')} />
                  <RankBars items={loadRanking} unit="count" showShare={false} limit={12} />
                </Card>
                <Card>
                  <CardHeader title={t('Динамика занятий по месяцам')} description={t('Запланированные занятия каждого преподавателя, включая проведённые и отменённые.')} />
                  <div className="h-72"><StackedBars rows={monthly} top={6} /></div>
                </Card>
              </div>

              <section className="mb-5">
                <div className="mb-3">
                  <h2 className="text-lg font-bold text-ink">{t('Преподаватели')}</h2>
                  <p className="text-sm text-ink-muted">{t('Фактические показатели расписания без оценки эффективности преподавателя.')}</p>
                </div>
                <TeacherTable teachers={data.teachers} />
              </section>

              <div className="mb-5 grid gap-4 lg:grid-cols-3">
                <BreakdownCard title={t('По филиалам')} rows={data.breakdowns.branch} />
                <BreakdownCard title={t('По направлениям')} rows={data.breakdowns.direction} />
                <Card>
                  <CardHeader title={t('Причины отмен')} description={t('Причина преподавателя выделена отдельно как факт.')}/>
                  {data.cancel_reasons.length ? (
                    <ul className="space-y-3">
                      {data.cancel_reasons.map(reason => (
                        <li key={reason.key} className="flex items-center justify-between gap-3 text-sm">
                          <span className="flex min-w-0 items-center gap-2 text-ink">
                            <span className="truncate">{t(reason.label)}</span>
                            {reason.teacher_fault && <Badge tone="warning">{t('По причине преподавателя')}</Badge>}
                          </span>
                          <strong>{reason.value}</strong>
                        </li>
                      ))}
                    </ul>
                  ) : <p className="py-8 text-center text-sm text-ink-muted">{t('Отмен за выбранный период нет')}</p>}
                </Card>
              </div>
            </>
          ) : (
            <Card><p className="py-10 text-center text-sm text-ink-muted">{t('Нет занятий за выбранный период')}</p></Card>
          )}
        </div>
      )}
    </>
  )
}

function ReportSelect({ label, value, onChange, options = [], all }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{label}</span>
      <Select value={value} onChange={event => onChange(event.target.value)} aria-label={label}>
        <option value="">{all}</option>
        {options.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
      </Select>
    </label>
  )
}

function SummaryCard({ icon: Icon, label, value, warning = false }) {
  return (
    <Card className="min-w-0">
      <div className={cn('mb-3 flex size-9 items-center justify-center rounded-md', warning ? 'bg-warning-50 text-warning-600' : 'bg-brand-50 text-brand-600')}>
        <Icon className="size-4.5" />
      </div>
      <p className="text-xl font-bold text-ink">{formatValue(value, 'count')}</p>
      <p className="mt-1 text-xs text-ink-muted">{label}</p>
    </Card>
  )
}

function TeacherTable({ teachers }) {
  const columns = [
    { key: 'name', header: t('Преподаватель'), primary: true, render: row => <span className="font-semibold">{row.name}</span> },
    { key: 'lessons_per_week', header: t('Занятий в неделю'), mobileAside: true, align: 'right', render: row => <Badge>{formatValue(row.lessons_per_week, 'count')}</Badge> },
    { key: 'students', header: t('Уникальных учеников'), align: 'right' },
    { key: 'fill_percent', header: t('Средняя заполняемость'), align: 'right', render: row => formatValue(row.fill_percent, 'percent') },
    { key: 'completed', header: t('Проведено / запланировано'), align: 'right', render: row => `${row.completed} / ${row.planned}` },
    { key: 'cancelled', header: t('Отменено'), align: 'right' },
    { key: 'teacher_cancelled', header: t('По причине преподавателя'), align: 'right', render: row => row.teacher_cancelled ? <Badge tone="warning">{row.teacher_cancelled}</Badge> : 0 },
  ]
  return <DataTable columns={columns} rows={teachers} />
}

function BreakdownCard({ title, rows = [] }) {
  return (
    <Card>
      <CardHeader title={title} />
      {rows.length ? (
        <ul className="space-y-3">
          {rows.map(row => (
            <li key={row.key ?? 'none'} className="rounded-md bg-surface-muted p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-sm font-semibold text-ink">{row.label}</span>
                <span className="text-sm font-bold text-ink">{row.planned}</span>
              </div>
              <p className="mt-1 text-xs text-ink-muted">
                {t('{teachers} преподавателей · {students} учеников · {completed} проведено', row)}
              </p>
            </li>
          ))}
        </ul>
      ) : <p className="py-8 text-center text-sm text-ink-muted">{t('Нет данных')}</p>}
    </Card>
  )
}
