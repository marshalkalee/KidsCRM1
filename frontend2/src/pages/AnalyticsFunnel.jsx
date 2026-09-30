import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, CardHeader, DataTable, Dropdown, ErrorState, PageHeader, Skeleton, Tabs, cn } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ExportButton, FunnelChart, breakdownLabel, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'

const STAGE_LABELS = {
  new: () => t('Заявки'),
  contacted: () => t('Связались'),
  trial_scheduled: () => t('Записаны на пробное'),
  trial_attended: () => t('Пришли на пробное'),
  purchased: () => t('Купили абонемент'),
}
const BY = [
  { key: 'source', get label() { return t('Источник') } },
  { key: 'direction', get label() { return t('Направление') } },
  { key: 'branch', get label() { return t('Филиал') } },
  { key: 'manager', get label() { return t('Ответственный') } },
]
const FILTERS = ['source', 'direction', 'manager']

const pct = (part, whole) => (whole ? Math.round((part * 1000) / whole) / 10 : null)

/**
 * «Воронка продаж» (TRU-115): новые заявки за период → связались →
 * пробное → пришли → купили. Продления сюда не входят (TRU-98). Клик по
 * «сейчас на этапе» открывает эти заявки в списке — отчёт ведёт к делу.
 */
export default function AnalyticsFunnel() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [by, setBy] = useState('source')

  const extra = new URLSearchParams(FILTERS.filter(k => params.get(k)).map(k => [k, params.get(k)])).toString()
  const { data, error } = useAnalyticsGet('funnel', extra, filters)
  const breakdown = useAnalyticsGet('funnel/by', `${extra}${extra ? '&' : ''}by=${by}`, filters)
  // Варианты фильтров берём из самих разрезов — в списке только то, что есть в заявках.
  const options = {
    source: useAnalyticsGet('funnel/by', 'by=source', filters).data?.items,
    direction: useAnalyticsGet('funnel/by', 'by=direction', filters).data?.items,
    manager: useAnalyticsGet('funnel/by', 'by=manager', filters).data?.items,
  }

  const summary = data?.funnel
  const previous = summary?.previous
  const period = data?.period

  function setFilter(key, value) {
    setParams(current => {
      const next = new URLSearchParams(current)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace: true })
  }

  function openStuck(stage) {
    const q = new URLSearchParams({ view: 'table', status: stage.key, created_from: period.start, created_to: period.end })
    FILTERS.forEach(key => {
      if (params.get(key)) q.set(key === 'manager' ? 'assigned_to' : key, params.get(key))
    })
    // Список заявок берёт несколько филиалов через запятую.
    if (filters.branches.length) q.set('branch', filters.branches.join(','))
    navigate(`/leads?${q}`)
  }

  const stages = summary?.stages.map(stage => ({
    ...stage,
    label: STAGE_LABELS[stage.key](),
    value: stage.count,
    // «Пришли → купили» — только среди пришедших: без пробного покупают отдельно.
    step: stage.key === 'purchased' && summary.stages[3].count
      ? Math.round((summary.purchased_after_trial * 100) / summary.stages[3].count)
      : undefined,
  }))

  return (
    <>
      <PageHeader
        title={t('Аналитика')}
        description={t('Воронка новых заявок · продления считаются отдельно')}
        actions={<ExportButton report="funnel" filters={filters} extra={extra} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={period} previous={data?.previous_period} />

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        {FILTERS.map(key => (
          <Dropdown
            key={key}
            size="sm"
            ariaLabel={BY.find(b => b.key === key).label}
            value={params.get(key) || ''}
            onChange={value => setFilter(key, value)}
            options={[
              { value: '', label: { source: t('Все источники'), direction: t('Все направления'), manager: t('Все ответственные') }[key] },
              ...(options[key] || []).filter(item => item.key).map(item => ({ value: item.key, label: breakdownLabel(item) })),
            ]}
          />
        ))}
      </div>

      {error ? (
        <Card><ErrorState /></Card>
      ) : !summary ? (
        <Skeleton className="h-96" />
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Tile label={t('Новых заявок')} value={summary.total} previous={previous?.total} />
            <Tile label={t('Дошли до пробного')} value={summary.stages[3].count} previous={previous?.stages[3].count} note={pct(summary.stages[3].count, summary.total) != null ? t('{p}% заявок', { p: formatValue(pct(summary.stages[3].count, summary.total), 'count') }) : null} />
            <Tile label={t('Купили')} value={summary.stages[4].count} previous={previous?.stages[4].count} note={summary.purchased_without_trial ? t('без пробного: {n}', { n: summary.purchased_without_trial }) : null} />
            <Tile label={t('Конверсия в покупку')} value={summary.conversion} unit="percent" previous={previous?.conversion} points />
          </div>

          <div className="grid gap-4 lg:grid-cols-5">
            <Card className="lg:col-span-2">
              <CardHeader title={t('Этапы')} description={t('Клик по «сейчас на этапе» — открыть эти заявки')} />
              {summary.total ? (
                <>
                  <FunnelChart stages={stages} onSelect={openStuck} />
                  <p className="mt-4 border-t border-line pt-3 text-xs text-ink-subtle">
                    {t('Думают: {thinking} · Отказались: {rejected}', { thinking: summary.thinking, rejected: summary.rejected })}
                  </p>
                </>
              ) : (
                <p className="py-10 text-center text-sm text-ink-muted">{t('За этот период новых заявок нет')}</p>
              )}
            </Card>
            <Card className="lg:col-span-3" padded={false}>
              <div className="p-5 pb-0">
                <CardHeader title={t('Где теряем')} description={t('Та же воронка в разрезе — от этапа к этапу')} />
                <Tabs tabs={BY} value={by} onChange={setBy} className="mb-3" />
              </div>
              <BreakdownTable items={breakdown.data?.items} loading={breakdown.loading} />
            </Card>
          </div>
        </>
      )}
    </>
  )
}

function Tile({ label, value, previous, unit = 'count', note, points = false }) {
  const diff = previous == null || value == null ? null : Number(value) - Number(previous)
  return (
    <Card className="min-w-0">
      <p className="text-[13px] font-semibold text-ink-muted">{label}</p>
      <p className="mt-2 truncate text-[22px] font-bold text-ink sm:text-[26px]">{formatValue(value, unit)}</p>
      <p className="mt-1 text-xs text-ink-subtle">
        {diff == null ? t('Не с чем сравнить') : (
          <span className={cn('font-semibold', diff > 0 ? 'text-success-600' : diff < 0 ? 'text-danger-600' : 'text-ink-muted')}>
            {diff > 0 ? '+' : ''}{formatValue(diff, 'count')}{points ? ` ${t('п.п.')}` : ''}
          </span>
        )}
        {diff != null && ` ${t('к прошлому периоду')}`}
        {note && <span className="block">{note}</span>}
      </p>
    </Card>
  )
}

function BreakdownTable({ items, loading }) {
  const columns = [
    { key: 'label', header: t('Разрез'), primary: true, render: row => breakdownLabel(row) },
    { key: 'total', header: t('Заявок'), align: 'right', mobileAside: true, render: row => formatValue(row.total, 'count') },
    { key: 'contacted', header: t('Связались'), align: 'right', render: row => rate(row, 'contacted') },
    { key: 'trial', header: t('Пробное'), align: 'right', render: row => rate(row, 'trial_attended') },
    { key: 'purchased', header: t('Купили'), align: 'right', render: row => formatValue(row.stages.purchased, 'count') },
    {
      key: 'conversion',
      header: t('Конверсия'),
      align: 'right',
      render: row => <span className="font-semibold text-ink">{formatValue(row.conversion, 'percent')}</span>,
    },
  ]
  return <DataTable columns={columns} rows={items || []} rowKey={row => row.key ?? 'none'} loading={loading && !items} empty={<p className="py-8 text-center text-sm text-ink-muted">{t('Нет заявок')}</p>} />
}

function rate(row, stage) {
  const value = pct(row.stages[stage], row.total)
  return value == null ? '—' : `${formatValue(value, 'percent')}`
}
