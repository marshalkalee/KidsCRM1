import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowDownRight, ArrowUpRight, Building2, Lock } from 'lucide-react'
import { Card, CardHeader, DataTable, Dropdown, EmptyState, ErrorState, PageHeader, Skeleton, cn } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ExportButton, MultiLineChart, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'

// Подписи колонок переводятся здесь, а не приходят русскими с бэка.
const LABELS = {
  revenue_per_child: () => t('Выручка на ребёнка'),
  revenue: () => t('Выручка'),
  average_check: () => t('Средний чек'),
  group_fill: () => t('Заполняемость групп'),
  attendance_rate: () => t('Доля посещений'),
  lead_conversion: () => t('Конверсия заявок'),
  debt_per_child: () => t('Долг на ребёнка'),
  debt_total: () => t('Задолженность'),
  active_children: () => t('Ходили на занятия'),
  new_leads: () => t('Новых заявок'),
}
const DEFAULT_COLUMNS = ['revenue_per_child', 'revenue', 'group_fill', 'lead_conversion', 'debt_per_child']
const TRENDS = ['revenue', 'average_check', 'attendance_rate', 'active_children', 'new_leads', 'group_fill', 'debt_total']

/**
 * «Филиалы» (TRU-128, тариф Network): филиалы в строках, метрики в
 * колонках. Честно сравнивать по относительным колонкам (на ребёнка, доли,
 * конверсия) — абсолютные рядом. Лучшее в колонке — зелёным, худшее — красным.
 */
export default function AnalyticsBranches() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const [params, setParams] = useSearchParams()
  const [trendMetric, setTrendMetric] = useState('revenue')
  const selected = (params.get('cols') || DEFAULT_COLUMNS.join(',')).split(',').filter(Boolean)
  const allowed = catalog?.features?.branch_compare !== false
  const { data, error } = useAnalyticsGet(allowed ? 'branches' : '', '', filters)
  const trend = useAnalyticsGet(allowed ? 'branches/trend' : '', `metric=${trendMetric}`, filters)

  function toggle(key) {
    const next = selected.includes(key) ? selected.filter(k => k !== key) : [...selected, key]
    if (!next.length) return
    setParams(current => {
      const updated = new URLSearchParams(current)
      updated.set('cols', next.join(','))
      return updated
    }, { replace: true })
  }

  const header = (
    <>
      <PageHeader
        title={t('Аналитика')}
        description={t('Где точка работает хорошо, где проседает')}
        actions={allowed && <ExportButton report="branches" filters={filters} />}
      />
      <AnalyticsNav />
    </>
  )

  if (catalog && !allowed) {
    return (
      <>
        {header}
        <Card><EmptyState icon={Lock} title={t('Сравнение филиалов — в тарифе Network')} description={t('Для сети из нескольких филиалов: таблица филиалов по всем метрикам и их динамика.')} /></Card>
      </>
    )
  }

  const columns = (data?.columns || []).filter(c => selected.includes(c.key))

  return (
    <>
      {header}
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      <Card className="mb-4">
        <p className="mb-2 text-[13px] font-semibold text-ink-muted">{t('Что сравнить')}</p>
        <div className="flex flex-wrap gap-2">
          {(data?.columns || []).map(column => {
            const on = selected.includes(column.key)
            return (
              <button
                key={column.key}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(column.key)}
                className={cn(
                  'rounded-full border px-3 py-1 text-[12px] font-semibold transition-colors',
                  on ? 'border-brand-200 bg-brand-50 text-brand-700' : 'border-line-strong text-ink-muted hover:border-brand-200',
                )}
              >
                {LABELS[column.key]?.() || column.label}
                {column.relative && <span className="ml-1 font-normal text-ink-subtle">· {t('отн.')}</span>}
              </button>
            )
          })}
        </div>
        <p className="mt-2 text-xs text-ink-subtle">{t('«отн.» — честно сравнивать между филиалами разного размера. Ребёнок — ходил на занятия в периоде.')}</p>
      </Card>

      {error ? (
        <Card><ErrorState /></Card>
      ) : !data ? (
        <Skeleton className="h-80" />
      ) : (
        <>
          {!data.comparable && (
            <Card className="mb-4 border-info-50 bg-info-50/40">
              <p className="flex items-center gap-2 text-sm text-ink-muted">
                <Building2 className="size-4 text-info-600" />
                {data.rows.length ? t('В выборке один филиал — сравнивать не с чем. Ниже его показатели.') : t('Филиалов нет.')}
              </p>
            </Card>
          )}
          <Card padded={false} className="mb-4">
            <CompareTable data={data} columns={columns} />
          </Card>
          {data.comparable && (
            <Card>
              <CardHeader
                title={t('Динамика по филиалам')}
                description={t('Одна метрика — линия на каждый филиал')}
                actions={
                  <div className="w-56">
                    <Dropdown size="sm" ariaLabel={t('Метрика')} value={trendMetric} onChange={setTrendMetric} options={TRENDS.map(key => ({ value: key, label: LABELS[key]() }))} />
                  </div>
                }
              />
              <div style={{ height: 300 }}>
                {trend.data ? (
                  <MultiLineChart
                    lines={trend.data.branches.map(b => ({ key: b.branch.id, label: b.branch.name, series: b.series }))}
                    unit={trend.data.branches[0]?.unit}
                    granularity={['group_fill', 'debt_total'].includes(trendMetric) ? 'day' : data.period.granularity}
                  />
                ) : <Skeleton className="h-full" />}
              </div>
            </Card>
          )}
        </>
      )}
    </>
  )
}

/** Лучший и худший филиал в колонке — по направлению «хорошо». */
function extremes(rows, column) {
  const values = rows.map(r => r.values[column.key].value).filter(v => v != null).map(Number)
  if (values.length < 2 || Math.min(...values) === Math.max(...values)) return {}
  const best = column.higher_is_better ? Math.max(...values) : Math.min(...values)
  const worst = column.higher_is_better ? Math.min(...values) : Math.max(...values)
  return { best, worst }
}

function CompareTable({ data, columns }) {
  const marks = Object.fromEntries(columns.map(c => [c.key, data.comparable ? extremes(data.rows, c) : {}]))
  const rows = [
    ...data.rows.map(row => ({ id: row.branch.id, name: row.branch.name, values: row.values })),
    ...(data.comparable ? [{ id: 'total', name: t('Всего'), values: data.total, total: true }] : []),
  ]
  const tableColumns = [
    {
      key: 'name',
      header: t('Филиал'),
      primary: true,
      render: row => <span className={cn('font-semibold', row.total ? 'text-ink-muted' : 'text-ink')}>{row.name}</span>,
    },
    ...columns.map(column => ({
      key: column.key,
      header: LABELS[column.key]?.() || column.label,
      align: 'right',
      render: row => <Cell value={row.values[column.key]} column={column} mark={row.total ? null : marks[column.key]} />,
    })),
  ]
  return <DataTable columns={tableColumns} rows={rows} rowKey={row => row.id} />
}

function Cell({ value, column, mark }) {
  const current = value.value == null ? null : Number(value.value)
  const before = value.previous == null ? null : Number(value.previous)
  const tone = mark && current != null
    ? current === mark.best ? 'bg-success-50 text-success-600' : current === mark.worst ? 'bg-danger-50 text-danger-600' : ''
    : ''
  const diff = current != null && before != null && before !== 0 ? Math.round(((current - before) * 1000) / Math.abs(before)) / 10 : null
  const good = diff == null || diff === 0 ? null : (diff > 0) === column.higher_is_better
  const Icon = diff > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <span className={cn('inline-flex flex-col items-end rounded-md px-2 py-1', tone)}>
      <span className="font-semibold">{formatValue(current, column.unit)}</span>
      {diff != null && diff !== 0 && (
        <span className={cn('inline-flex items-center text-[11px]', good ? 'text-success-600' : 'text-danger-600')}>
          <Icon className="size-3" />{formatValue(Math.abs(diff), 'percent')}
        </span>
      )}
    </span>
  )
}
