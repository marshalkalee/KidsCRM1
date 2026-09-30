import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, Megaphone, Merge, Percent, TriangleAlert, UsersRound } from 'lucide-react'
import { AnalyticsNav, AnalyticsToolbar, ExportButton, RankBars, TrendChart, useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet } from '../components/analytics'
import { Badge, Card, CardHeader, ErrorState, PageHeader, Select, Skeleton, cn } from '../ui'
import { t } from '../i18n'
import { useSession } from '../session/SessionContext'

const FILTER_KEYS = ['direction', 'teacher', 'weekday', 'time']

export default function AnalyticsGroups() {
  const filters = useAnalyticsFilters()
  const { can } = useSession()
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
  const report = useAnalyticsGet('group-occupancy', extra, filters)
  const data = report.data

  function setFilter(key, value) {
    setParams(current => {
      const next = new URLSearchParams(current)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace: true })
  }

  return (
    <>
      <PageHeader
        title={t('Заполняемость групп')}
        description={t('Занятость, недобор и динамика состава')}
        actions={<ExportButton report="group_occupancy" filters={filters} extra={extra} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      <Card className="mb-5">
        <CardHeader title={t('Разрез отчёта')} description={t('Фильтры применяются к сводке, списку и Excel-файлу.')} />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ReportSelect label={t('Направление')} value={params.get('direction') || ''} onChange={value => setFilter('direction', value)} options={data?.filters?.directions} all={t('Все направления')} />
          <ReportSelect label={t('Преподаватель')} value={params.get('teacher') || ''} onChange={value => setFilter('teacher', value)} options={data?.filters?.teachers} all={t('Все преподаватели')} />
          <ReportSelect label={t('День недели')} value={params.get('weekday') || ''} onChange={value => setFilter('weekday', value)} options={data?.filters?.weekdays} all={t('Все дни')} />
          <ReportSelect label={t('Время')} value={params.get('time') || ''} onChange={value => setFilter('time', value)} options={data?.filters?.times} all={t('Любое время')} />
        </div>
      </Card>

      {report.error && !data ? (
        <Card><ErrorState onRetry={report.reload} /></Card>
      ) : !data ? (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">{[1, 2, 3, 4].map(item => <Skeleton key={item} className="h-28" />)}</div>
      ) : (
        <div className={cn(report.loading && 'opacity-60 transition-opacity')}>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <SummaryCard icon={Percent} label={t('Средняя заполняемость')} value={percent(data.summary.percent)} />
            <SummaryCard icon={UsersRound} label={t('Занято / вместимость')} value={`${data.summary.occupied} / ${data.summary.capacity}`} />
            <SummaryCard icon={TriangleAlert} label={t('Недозаполненных групп')} value={data.summary.underfilled_count} warning={data.summary.underfilled_count > 0} />
            <SummaryCard icon={Percent} label={t('Порог недозаполненности')} value={`${data.threshold}%`} />
          </div>

          <div className="mb-5 grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title={t('Динамика по месяцам')} description={t('Состав на конец каждого месяца выбранного периода.')} />
              <div className="h-64"><TrendChart series={data.trend} unit="percent" granularity="month" label={t('Заполняемость групп')} /></div>
            </Card>
            <BreakdownCard title={t('По филиалам')} rows={data.breakdowns.branch} />
          </div>

          <section className="mb-6">
            <h2 className="mb-3 text-[13px] font-bold uppercase tracking-[0.06em] text-ink-subtle">{t('Разрезы заполняемости')}</h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <BreakdownCard title={t('По направлениям')} rows={data.breakdowns.direction} />
              <BreakdownCard title={t('По преподавателям')} rows={data.breakdowns.teacher} />
              <BreakdownCard title={t('По дням недели')} rows={data.breakdowns.weekday} />
              <BreakdownCard title={t('По времени')} rows={data.breakdowns.time} />
            </div>
          </section>

          <section className="mb-6">
            <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="text-lg font-bold text-ink">{t('Недозаполненные группы')}</h2>
                <p className="text-sm text-ink-muted">{t('Ниже установленного порога — кандидаты на продвижение или объединение.')}</p>
              </div>
              {can('can_manage_org_settings') && <Link to="/settings/organization" className="text-sm font-semibold text-brand-600 hover:text-brand-700">{t('Изменить порог')}</Link>}
            </div>
            {data.underfilled.length ? (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {data.underfilled.map(group => <GroupCard key={group.id} group={group} recommendation />)}
              </div>
            ) : (
              <Card className="text-sm text-ink-muted">{t('Все активные группы заполнены не ниже порога.')}</Card>
            )}
          </section>

          <section className="mb-6">
            <div className="mb-3">
              <h2 className="text-lg font-bold text-ink">{t('Все группы')}</h2>
              <p className="text-sm text-ink-muted">{t('{n} групп в выбранном разрезе', { n: data.summary.groups_count })}</p>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {data.groups.map(group => <GroupCard key={group.id} group={group} />)}
            </div>
          </section>
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
        {options.map(option => <option key={option.id} value={option.id}>{t(option.name)}</option>)}
      </Select>
    </label>
  )
}

function SummaryCard({ icon: Icon, label, value, warning }) {
  return (
    <Card className="min-w-0">
      <div className={cn('mb-3 flex size-9 items-center justify-center rounded-md', warning ? 'bg-warning-50 text-warning-600' : 'bg-brand-50 text-brand-600')}><Icon className="size-4.5" /></div>
      <p className="text-xl font-bold text-ink">{value}</p>
      <p className="mt-1 text-xs text-ink-muted">{label}</p>
    </Card>
  )
}

function BreakdownCard({ title, rows }) {
  return (
    <Card>
      <CardHeader title={title} />
      {rows?.length ? <RankBars items={rows} unit="percent" max={100} showShare={false} limit={10} /> : <p className="py-8 text-center text-sm text-ink-muted">{t('Нет данных')}</p>}
    </Card>
  )
}

function GroupCard({ group, recommendation = false }) {
  const tone = group.is_underfilled ? 'warning' : group.percent >= 100 ? 'danger' : 'success'
  return (
    <Card className="flex min-w-0 flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/groups/${group.id}`} className="font-bold text-ink hover:text-brand-600">{group.name}</Link>
          <p className="mt-0.5 truncate text-xs text-ink-muted">{group.branch} · {group.direction}</p>
        </div>
        <Badge tone={tone}>{group.occupied}/{group.capacity} · {group.percent}%</Badge>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-muted">
        <div className={cn('h-full rounded-full', group.is_underfilled ? 'bg-warning-600' : group.percent >= 100 ? 'bg-danger-600' : 'bg-success-600')} style={{ width: `${Math.min(group.percent, 100)}%` }} />
      </div>
      {recommendation && (
        <div className="mt-4 flex items-start gap-2 rounded-md bg-surface-muted p-3 text-xs text-ink-muted">
          {group.suggested_action === 'merge' ? <Merge className="mt-0.5 size-4 shrink-0 text-info-600" /> : <Megaphone className="mt-0.5 size-4 shrink-0 text-brand-600" />}
          <div>
            <p className="font-semibold text-ink">{group.suggested_action === 'merge' ? t('Рассмотреть объединение') : t('Продвигать набор')}</p>
            {group.merge_candidates.length > 0 && <p className="mt-0.5">{t('Подходящие группы: {groups}', { groups: group.merge_candidates.map(item => item.name).join(', ') })}</p>}
          </div>
        </div>
      )}
      <Link to={`/groups/${group.id}`} className="mt-4 inline-flex items-center gap-1 self-end text-xs font-semibold text-brand-600 hover:text-brand-700">
        {t('Открыть группу')} <ArrowRight className="size-3.5" />
      </Link>
    </Card>
  )
}

function percent(value) {
  return value == null ? '—' : `${value}%`
}
