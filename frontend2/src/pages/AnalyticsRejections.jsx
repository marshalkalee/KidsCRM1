import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, DataTable, Dropdown, ErrorState, PageHeader, Skeleton, Tabs, formatDate } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, DonutChart, ExportButton, PALETTE, StackedBars, breakdownLabel, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'

const KINDS = [
  { key: 'new', get label() { return t('Новые заявки') } },
  { key: 'renewal', get label() { return t('Продления') } },
]
const STAGE_LABELS = {
  before_contact: () => t('До разговора'),
  after_contact: () => t('После звонка'),
  trial_booked: () => t('Записан на пробное'),
  after_trial: () => t('После пробного'),
}
const FILTERS = ['kind', 'source', 'direction']

/**
 * «Отказы» (TRU-117): почему отказываются и на каком этапе. «Не пришёл на
 * пробное» — потеря контакта, а не возражение: считается отдельно.
 * Комментарии — списком: в свободном тексте бывает то, чего нет в справочнике.
 */
export default function AnalyticsRejections() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind') === 'renewal' ? 'renewal' : 'new'
  const extra = new URLSearchParams(FILTERS.filter(k => params.get(k)).map(k => [k, params.get(k)])).toString()
  const { data, error } = useAnalyticsGet('rejections', extra, filters)
  const bySource = useAnalyticsGet('rejections/by', `${extra}${extra ? '&' : ''}by=source`, filters)
  const options = {
    source: useAnalyticsGet('funnel/by', 'by=source', filters).data?.items || [],
    direction: useAnalyticsGet('funnel/by', 'by=direction', filters).data?.items || [],
  }

  function set(key, value) {
    setParams(current => {
      const next = new URLSearchParams(current)
      if (value && !(key === 'kind' && value === 'new')) next.set(key, value)
      else next.delete(key)
      return next
    }, { replace: true })
  }

  const summary = data?.summary
  const top = summary?.reasons[0]
  const afterTrial = summary?.stages.find(s => s.key === 'after_trial')?.value || 0

  return (
    <>
      <PageHeader
        title={t('Аналитика')}
        description={t('Почему отказываются и на каком этапе')}
        actions={<ExportButton report="rejections" filters={filters} extra={extra} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
        <Tabs tabs={KINDS} value={kind} onChange={value => set('kind', value)} className="lg:mr-auto" />
        {kind === 'new' && ['source', 'direction'].map(key => (
          <div key={key} className="lg:w-60">
            <Dropdown
              size="sm"
              ariaLabel={key === 'source' ? t('Источник') : t('Направление')}
              value={params.get(key) || ''}
              onChange={value => set(key, value)}
              options={[
                { value: '', label: key === 'source' ? t('Все источники') : t('Все направления') },
                ...options[key].filter(i => i.key).map(i => ({ value: i.key, label: breakdownLabel(i) })),
              ]}
            />
          </div>
        ))}
      </div>

      {error ? (
        <Card><ErrorState /></Card>
      ) : !summary ? (
        <Skeleton className="h-96" />
      ) : !summary.total ? (
        <Card><p className="py-10 text-center text-sm text-ink-muted">{t('За этот период отказов нет')}</p></Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Tile label={t('Отказов')} value={formatValue(summary.real, 'count')} note={t('без потери контакта')} />
            <Tile label={t('Потеря контакта')} value={formatValue(summary.lost_contact, 'count')} note={t('не пришли на пробное — не возражение')} />
            <Tile label={t('Главная причина')} value={top ? breakdownLabel(top) : '—'} note={top ? t('{p}% отказов', { p: formatValue(top.share, 'count') }) : null} />
            <Tile label={t('После пробного')} value={formatValue(afterTrial, 'count')} note={summary.real ? t('{p}% отказов — про само занятие', { p: formatValue(Math.round((afterTrial * 1000) / summary.real) / 10, 'count') }) : null} />
          </div>

          <div className="mb-4 grid gap-4 lg:grid-cols-5">
            <Card className="min-w-0 lg:col-span-2">
              <CardHeader title={t('Причины')} description={t('Без потери контакта')} />
              {summary.reasons.length ? (
                <DonutChart items={summary.reasons} unit="count" centerLabel={t('отказов')} />
              ) : <p className="py-8 text-center text-sm text-ink-muted">{t('Содержательных отказов нет')}</p>}
            </Card>
            <Card className="min-w-0 lg:col-span-3">
              <CardHeader title={t('Причина × этап')} description={t('На каком шаге отказались: сразу после звонка — про цену и ожидания, после пробного — про занятие')} />
              <StageMatrix reasons={summary.reasons} stages={summary.stages} />
            </Card>
          </div>

          <div className="mb-4 grid gap-4 lg:grid-cols-2">
            <Card className="min-w-0">
              <CardHeader title={t('Отказы по месяцам')} description={t('Растёт ли доля «дорого» после повышения цен')} />
              <div style={{ height: 280 }}>
                {summary.by_month.length ? <StackedBars rows={summary.by_month} /> : null}
              </div>
            </Card>
            <Card padded={false} className="min-w-0">
              <div className="p-5 pb-0"><CardHeader title={t('По источникам')} description={t('Сколько отказов и главная причина')} /></div>
              <DataTable
                columns={[
                  { key: 'label', header: t('Источник'), primary: true, render: row => breakdownLabel(row) },
                  { key: 'value', header: t('Отказов'), align: 'right', mobileAside: true, render: row => formatValue(row.value, 'count') },
                  { key: 'top', header: t('Главная причина'), render: row => `${row.top_reason || t('Не указана')} · ${formatValue(row.top_share, 'percent')}` },
                ]}
                rows={bySource.data?.items || []}
                rowKey={row => row.key ?? 'none'}
                loading={bySource.loading && !bySource.data}
                empty={<p className="py-8 text-center text-sm text-ink-muted">{t('Нет отказов')}</p>}
              />
            </Card>
          </div>

          <Comments rows={data.comments} />
        </>
      )}
    </>
  )
}

const COMMENTS_PAGE = 10

/** Комментарии к отказам — по 10, «Показать ещё» (с сервера — до 100 свежих). */
function Comments({ rows }) {
  const [shown, setShown] = useState(COMMENTS_PAGE)
  return (
    <Card>
      <CardHeader title={t('Комментарии к отказам')} description={t('Что говорили своими словами — свежие сверху')} />
      {rows.length ? (
        <>
          <ul className="divide-y divide-line">
            {rows.slice(0, shown).map(row => (
              <li key={`${row.lead_id}-${row.date}`} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-subtle">
                  <span>{formatDate(row.date)}</span>
                  <Link to={`/leads/${row.lead_id}`} className="font-semibold text-ink hover:text-brand-600">{row.lead}</Link>
                  <Badge tone={row.lost_contact ? 'warning' : 'neutral'}>{row.reason || t('Не указана')}</Badge>
                  <span>{row.stage}</span>
                  {row.author && <span>· {row.author}</span>}
                </div>
                <p className="mt-1 text-sm text-ink">{row.comment}</p>
              </li>
            ))}
          </ul>
          {shown < rows.length && (
            <div className="mt-4 text-center">
              <Button size="sm" onClick={() => setShown(n => n + COMMENTS_PAGE * 2)}>
                {t('Показать ещё ({n})', { n: rows.length - shown })}
              </Button>
            </div>
          )}
        </>
      ) : <p className="py-6 text-center text-sm text-ink-muted">{t('Комментариев к отказам за период нет')}</p>}
    </Card>
  )
}

function Tile({ label, value, note }) {
  return (
    <Card className="min-w-0">
      <p className="text-[13px] font-semibold text-ink-muted">{label}</p>
      <p className="mt-2 truncate text-[20px] font-bold text-ink sm:text-[24px]">{value}</p>
      {note && <p className="mt-1 text-xs text-ink-subtle">{note}</p>}
    </Card>
  )
}

/** Таблица «причина × этап»: чем темнее клетка, тем больше отказов. */
function StageMatrix({ reasons, stages }) {
  const max = Math.max(1, ...reasons.flatMap(r => Object.values(r.stages)))
  return (
    <div className="overflow-x-auto">
      {/* table-fixed: на телефоне колонки делят ширину, а не распирают страницу. */}
      <table className="w-full table-fixed border-separate border-spacing-1 text-[12px] sm:text-[13px]">
        <thead>
          <tr>
            <th className="w-[30%]" />
            {stages.map(stage => (
              <th key={stage.key} className="px-0.5 pb-1 text-center text-[10px] font-semibold leading-tight text-ink-subtle sm:text-[11px]">{STAGE_LABELS[stage.key]()}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {reasons.map(reason => (
            <tr key={reason.key ?? 'none'}>
              <td className="truncate pr-1 text-ink">{breakdownLabel(reason)}</td>
              {stages.map(stage => {
                const value = reason.stages[stage.key]
                return (
                  <td key={stage.key} className="h-9 rounded-md text-center font-semibold" style={{ background: value ? PALETTE[0] : 'var(--color-surface-muted)', color: value / max > 0.55 ? 'white' : 'var(--color-ink)', opacity: value ? 0.25 + (value / max) * 0.75 : 1 }}>
                    {value || ''}
                  </td>
                )
              })}
            </tr>
          ))}
          <tr>
            <td className="pr-2 text-xs font-semibold text-ink-subtle">{t('Итого')}</td>
            {stages.map(stage => <td key={stage.key} className="text-center text-xs font-bold text-ink">{stage.value}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}
