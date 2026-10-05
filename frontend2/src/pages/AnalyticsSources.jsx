import { useSearchParams } from 'react-router-dom'
import { Info } from 'lucide-react'
import { Badge, Card, CardHeader, DataTable, Dropdown, ErrorState, PageHeader, Skeleton } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ExportButton, QualityBars, StackedBars, breakdownLabel, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'

/**
 * «Источники» (TRU-116): не «откуда больше заявок», а «откуда клиенты».
 * По каждому источнику — та же воронка, что в «Воронке продаж»: сколько
 * дошли до пробного, сколько купили, конверсия и средний чек. Стоимость
 * источника не считаем — расходов на рекламу в системе нет, так и пишем.
 */
export default function AnalyticsSources() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const [params, setParams] = useSearchParams()
  const direction = params.get('direction') || ''
  const extra = direction ? `direction=${direction}` : ''
  const { data, error } = useAnalyticsGet('sources', extra, filters)
  const directions = useAnalyticsGet('funnel/by', 'by=direction', filters).data?.items || []

  function setDirection(value) {
    setParams(current => {
      const next = new URLSearchParams(current)
      if (value) next.set('direction', value)
      else next.delete('direction')
      return next
    }, { replace: true })
  }

  const items = data?.items
  const monthly = (data?.by_month || []).map(row => ({ month: row.month, key: row.source, label: row.label, value: row.leads }))
  const best = items?.filter(i => !i.small_sample && i.purchased).sort((a, b) => b.conversion - a.conversion)[0]

  return (
    <>
      <PageHeader
        title={t('Аналитика')}
        description={t('Какой источник приносит клиентов, а не только заявки')}
        actions={<ExportButton report="sources" filters={filters} extra={extra} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="sm:w-72">
          <Dropdown
            size="sm"
            ariaLabel={t('Направление')}
            value={direction}
            onChange={setDirection}
            options={[{ value: '', label: t('Все направления') }, ...directions.filter(d => d.key).map(d => ({ value: d.key, label: breakdownLabel(d) }))]}
          />
        </div>
        <p className="flex items-start gap-2 text-[13px] text-ink-muted">
          <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
          {t('Стоимость заявки и клиента не считаем: расходов на рекламу в системе нет. Отчёт показывает качество источника, а не окупаемость.')}
        </p>
      </div>

      {error ? (
        <Card><ErrorState /></Card>
      ) : !items ? (
        <Skeleton className="h-96" />
      ) : !items.length ? (
        <Card><p className="py-10 text-center text-sm text-ink-muted">{t('За этот период новых заявок нет')}</p></Card>
      ) : (
        <>
          {best && (
            <Card className="mb-4 border-brand-100 bg-gradient-to-br from-brand-50 to-surface">
              <p className="text-[13px] text-ink-muted">{t('Лучше всего покупают из источника')}</p>
              <p className="mt-1 text-xl font-bold text-ink">
                {breakdownLabel(best)} · {formatValue(best.conversion, 'percent')}
              </p>
              <p className="mt-0.5 text-xs text-ink-subtle">
                {t('{leads} заявок → {bought} купили', { leads: best.leads, bought: best.purchased })}
                {best.avg_check && ` · ${t('средний чек {sum}', { sum: formatValue(best.avg_check, 'money') })}`}
              </p>
            </Card>
          )}
          <div className="mb-4 grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title={t('Заявки и покупки')} description={t('Светлая полоса — заявки, яркая — сколько купили')} />
              <QualityBars items={items} />
              <p className="mt-4 text-xs text-ink-subtle">
                {t('«Мало данных» — меньше {n} заявок: по ним рано делать выводы.', { n: data.small_sample })}
              </p>
            </Card>
            <Card>
              <CardHeader title={t('Заявки по месяцам')} description={t('Как меняется вклад каналов')} />
              <div style={{ height: 300 }}>
                {monthly.length ? <StackedBars rows={monthly} /> : null}
              </div>
            </Card>
          </div>
          <Card padded={false}>
            <div className="p-5 pb-0"><CardHeader title={t('Все источники')} description={t('Новые заявки, созданные за период; продления не входят')} /></div>
            <SourcesTable items={items} />
          </Card>
          {data.campaigns?.length > 0 && (
            <Card padded={false} className="mt-4">
              <div className="p-5 pb-0"><CardHeader title={t('Какие публикации приводят клиентов')} description={t('Заявки, пришедшие по ссылке с кодом публикации или отмеченные вручную')} /></div>
              <SourcesTable items={data.campaigns} header={t('Публикация')} />
            </Card>
          )}
        </>
      )}
    </>
  )
}

function SourcesTable({ items, header = t('Источник') }) {
  const columns = [
    {
      key: 'label',
      header,
      primary: true,
      render: row => (
        <span className="flex items-center gap-2">
          {breakdownLabel(row)}
          {row.source && <span className="text-xs text-ink-muted">{t(row.source)}</span>}
          {row.small_sample && <Badge tone="warning">{t('мало данных')}</Badge>}
        </span>
      ),
    },
    { key: 'leads', header: t('Заявок'), align: 'right', mobileAside: true, render: row => formatValue(row.leads, 'count') },
    { key: 'trial_rate', header: t('До пробного'), align: 'right', render: row => formatValue(row.trial_rate, 'percent') },
    { key: 'purchased', header: t('Купили'), align: 'right', render: row => formatValue(row.purchased, 'count') },
    { key: 'conversion', header: t('Конверсия'), align: 'right', render: row => <span className="font-semibold text-ink">{formatValue(row.conversion, 'percent')}</span> },
    { key: 'avg_check', header: t('Средний чек'), align: 'right', render: row => formatValue(row.avg_check, 'money') },
  ]
  return <DataTable columns={columns} rows={items} rowKey={row => row.key ?? 'none'} />
}
