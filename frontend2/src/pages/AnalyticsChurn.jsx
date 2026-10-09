import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ClipboardPlus, Info, MessageCircle, Phone } from 'lucide-react'
import api from '../api/axios'
import { Badge, Button, Card, CardHeader, DataTable, ErrorState, PageHeader, Skeleton, Tabs, apiErrorMessage, cn, formatDate, useToast } from '../ui'
import { locale, t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ExportButton, MultiLineChart, PALETTE, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'

const LISTS = [
  { key: 'departed', get label() { return t('Ушли') } },
  { key: 'not_renewed', get label() { return t('Не продлили') } },
]
const DIMENSIONS = [
  { key: 'branch', get label() { return t('Филиал') } },
  { key: 'direction', get label() { return t('Направление') } },
  { key: 'group', get label() { return t('Группа') } },
  { key: 'teacher', get label() { return t('Преподаватель') } },
  { key: 'lifetime', get label() { return t('Срок жизни') } },
  { key: 'reason', get label() { return t('Причина ухода') } },
]
const LIFETIME_LABELS = {
  under_3: () => t('До 3 месяцев'),
  '3_6': () => t('3–6 месяцев'),
  '6_12': () => t('6–12 месяцев'),
  '12_24': () => t('1–2 года'),
  over_24: () => t('Больше 2 лет'),
}
const CHILD_STATES = {
  active: { tone: 'success', label: () => t('Ходит дальше') },
  departed: { tone: 'danger', label: () => t('Ушёл') },
  summer: { tone: 'info', label: () => t('Пауза на лето') },
  recent: { tone: 'warning', label: () => t('В риск-листе') },
}

/**
 * «Отток» (TRU-127, ТЗ раздел 7): кто ушёл за период — с контактами, чтобы
 * позвонить и создать задачу на возврат. Ушёл — нет активного абонемента
 * дольше N дней (настройка центра), летом — пауза до 30 сентября, а не
 * уход; месяц сравниваем с тем же месяцем прошлого года. Кто ушёл недавно
 * и ещё может остаться — в риск-листе, здесь его нет. Расчёт —
 * analytics/churn.py.
 */
export default function AnalyticsChurn() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const { data, error, loading } = useAnalyticsGet('churn', '', filters)
  const [list, setList] = useState('departed')
  const [dimension, setDimension] = useState('reason')

  const summary = data?.summary
  const rules = data?.rules

  return (
    <>
      <PageHeader
        title={t('Аналитика')}
        description={t('Кто ушёл и почему — чтобы позвонить и вернуть')}
        actions={<ExportButton report="churn" filters={filters} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      {error ? (
        <Card><ErrorState /></Card>
      ) : !summary ? (
        <Skeleton className="h-96" />
      ) : (
        <div className={cn('transition-opacity', loading && 'opacity-60')}>
          <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Tile
              label={t('Ушли')}
              value={formatValue(summary.departed, 'count')}
              note={t('{rate} из {active} ходивших; уже вернулись: {returned}', { rate: formatValue(summary.rate, 'percent'), active: summary.active, returned: summary.returned })}
            />
            <Tile
              label={t('Год назад')}
              value={formatValue(summary.previous_year.rate, 'percent')}
              note={t('ушли {departed} из {active} за те же даты', { departed: summary.previous_year.departed, active: summary.previous_year.active })}
            />
            <Tile
              label={t('Средний срок жизни клиента')}
              value={data.lifetime.year.departed ? t('{n} мес.', { n: formatValue(data.lifetime.year.average_months, 'count') }) : '—'}
              note={t('ушедших за 12 месяцев; за период — {n} мес.', { n: formatValue(data.lifetime.period.average_months, 'count') })}
            />
            <Tile
              label={t('Пауза на лето')}
              value={formatValue(summary.summer_waiting, 'count')}
              note={t('ждём до 30 сентября; вернулись после лета: {n}', { n: summary.summer_returned })}
            />
          </div>
          <RulesNote summary={summary} rules={rules} />

          <div className="mb-4 grid gap-4 lg:grid-cols-5">
            <Card className="min-w-0 lg:col-span-3">
              <CardHeader title={t('По месяцам')} description={t('Доля ушедших из ходивших в месяце — и тот же месяц год назад')} />
              <div style={{ height: 280 }}>
                <MultiLineChart
                  unit="percent"
                  granularity="month"
                  lines={[
                    { key: 'current', label: t('Этот год'), series: data.trend.map(row => ({ date: row.month, value: row.rate })) },
                    { key: 'previous', label: t('Год назад'), series: data.trend.map(row => ({ date: row.month, value: row.previous_year.rate })) },
                  ]}
                />
              </div>
              <TrendNote trend={data.trend} />
            </Card>
            <Card className="min-w-0 lg:col-span-2">
              <CardHeader title={t('Сколько прожил клиент')} description={t('От первого абонемента до ухода, ушедшие за 12 месяцев')} />
              <LifetimeBars lifetime={data.lifetime.year} />
            </Card>
          </div>

          <Card padded={false} className="mb-4">
            <div className="p-5 pb-3">
              <CardHeader title={t('Кому позвонить')} description={t('Не вернувшиеся — сверху, свежие уходы — первыми')} />
              <Tabs tabs={LISTS} value={list} onChange={setList} />
            </div>
            {list === 'departed'
              ? <DepartedTable items={data.items} filters={filters} />
              : <NotRenewedTable items={data.not_renewed} graceDays={rules.grace_days} />}
          </Card>

          <Card padded={false}>
            <div className="p-5 pb-3">
              <CardHeader title={t('Разрезы')} description={t('Откуда и почему уходят, сколько успели проходить')} />
              <Tabs tabs={DIMENSIONS} value={dimension} onChange={setDimension} />
              {dimension === 'teacher' && (
                <p className="mt-3 flex items-start gap-2 rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-ink">
                  <Info className="mt-0.5 size-4 shrink-0 text-warning-600" />
                  {t('Это не рейтинг преподавателей. Группа — та, где ребёнок ходил по последнему абонементу; ребёнок у двух преподавателей учитывается у обоих.')}
                </p>
              )}
            </div>
            <BreakdownTable dimension={dimension} rows={data.breakdowns[dimension]} />
          </Card>
        </div>
      )}
    </>
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

function RulesNote({ summary, rules }) {
  return (
    <div className="mb-4 flex items-start gap-2 text-[13px] text-ink-muted">
      <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
      <p>
        {t('Ушёл — нет активного абонемента дольше {days} дней после окончания последнего или отмечен «ушёл». Дата ухода — окончание последнего абонемента.', { days: rules.inactive_days })}
        {' '}
        {rules.summer_pause
          ? t('Летом (июнь–август) — пауза до 30 сентября: вернулся до неё — не уходил.')
          : t('Летняя пауза выключена: летние уходы считаются сразу.')}
        {' '}
        {summary.recent > 0 && (
          <>
            {t('Ещё не ушли, абонемент кончился недавно: {n} —', { n: summary.recent })}{' '}
            <Link to="/analytics/risk" className="font-semibold text-brand-600 hover:text-brand-700">{t('они в риск-листе')}</Link>.{' '}
          </>
        )}
        <Link to="/settings/organization" className="font-semibold text-brand-600 hover:text-brand-700">{t('Настроить порог')}</Link>
      </p>
    </div>
  )
}

function TrendNote({ trend }) {
  const open = trend.filter(row => !row.complete)
  if (!open.length) return null
  return (
    <p className="mt-2 text-xs text-ink-subtle">
      {t('Последние месяцы дособираются: {months} — порог или летняя пауза ещё не прошли.', { months: open.map(row => formatMonth(row.month)).join(', ') })}
    </p>
  )
}

function LifetimeBars({ lifetime }) {
  if (!lifetime.departed) {
    return <p className="py-8 text-center text-sm text-ink-muted">{t('Ушедших за 12 месяцев нет')}</p>
  }
  const max = Math.max(1, ...lifetime.buckets.map(row => row.value))
  return (
    <>
      <ul className="space-y-3">
        {lifetime.buckets.map(row => (
          <li key={row.key}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate text-ink">{LIFETIME_LABELS[row.key]?.() || row.label}</span>
              <span className="shrink-0 font-semibold text-ink">
                {formatValue(row.value, 'count')}
                <span className="ml-1.5 text-xs font-normal text-ink-subtle">{formatValue(row.share, 'percent')}</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full" style={{ width: `${(row.value / max) * 100}%`, background: row.key === 'under_3' ? 'var(--color-warning-600)' : PALETTE[0] }} />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs text-ink-subtle">
        {t('В среднем {avg} мес., медиана {median} мес. Уходят в первые 3 месяца — вопрос удержания; через годы — естественный цикл. Срок — с первого абонемента в системе.', {
          avg: formatValue(lifetime.average_months, 'count'),
          median: formatValue(lifetime.median_months, 'count'),
        })}
      </p>
    </>
  )
}

function ContactActions({ item, children }) {
  const phone = item.phone || item.whatsapp
  const whatsapp = (item.whatsapp || item.phone || '').replace(/\D/g, '')
  return (
    <div className="flex flex-wrap gap-2">
      {phone && <a href={`tel:${phone}`} className="font-btn inline-flex h-8 items-center gap-1.5 rounded-md border-[1.5px] border-line-strong px-3 text-xs font-semibold text-ink-muted hover:border-brand-300"><Phone className="size-4" />{t('Позвонить')}</a>}
      {whatsapp && <a href={`https://wa.me/${whatsapp}`} target="_blank" rel="noreferrer" className="font-btn inline-flex h-8 items-center gap-1.5 rounded-md bg-success-50 px-3 text-xs font-semibold text-success-600"><MessageCircle className="size-4" />WhatsApp</a>}
      {children}
      {!phone && !whatsapp && !children && <span className="text-xs text-ink-subtle">{t('Нет контакта')}</span>}
    </div>
  )
}

function WinbackButton({ item, filters }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const query = filters.query ? `?${filters.query}` : ''

  async function createTask() {
    setBusy(true)
    try {
      const { data } = await api.post(`analytics/churn/${item.id}/task/${query}`)
      toast.success(data.created ? t('Задача на возврат создана') : t('Задача на возврат уже есть'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return <Button icon={ClipboardPlus} size="sm" loading={busy} onClick={createTask}>{t('Задача на возврат')}</Button>
}

function DepartedTable({ items, filters }) {
  const columns = [
    {
      key: 'name',
      header: t('Ребёнок'),
      primary: true,
      render: item => (
        <div className="min-w-0">
          <Link to={`/children/${item.id}`} className="font-semibold text-ink hover:text-brand-600">{item.name}</Link>
          <p className="text-xs text-ink-muted">{[item.branch, item.direction, item.group].filter(Boolean).join(' · ')}</p>
          {item.parent && <p className="text-xs text-ink-subtle">{item.parent}</p>}
        </div>
      ),
    },
    {
      key: 'left_on',
      header: t('Ушёл'),
      mobileAside: true,
      render: item => (
        <div>
          <span>{formatDate(item.left_on)}</span>
          {item.returned_on && <div className="mt-1"><Badge tone="success">{t('Вернулся {date}', { date: formatDate(item.returned_on) })}</Badge></div>}
        </div>
      ),
    },
    { key: 'lifetime', header: t('Ходил'), align: 'right', render: item => t('{n} мес.', { n: formatValue(item.lifetime_months, 'count') }) },
    {
      key: 'reason',
      header: t('Причина ухода'),
      render: item => (item.marked_left
        ? (item.reason || <span className="text-ink-subtle">{t('Причина не указана')}</span>)
        : <Badge tone="warning">{t('Не отмечен ушедшим')}</Badge>),
    },
    {
      key: 'actions',
      header: '',
      render: item => (
        <ContactActions item={item}>
          {!item.returned_on && <WinbackButton item={item} filters={filters} />}
        </ContactActions>
      ),
    },
  ]
  return (
    <DataTable
      columns={columns}
      rows={items}
      rowKey={item => `${item.id}-${item.left_on}`}
      empty={<p className="py-8 text-center text-sm text-ink-muted">{t('За этот период никто не ушёл')}</p>}
    />
  )
}

function NotRenewedTable({ items, graceDays }) {
  const columns = [
    {
      key: 'name',
      header: t('Ребёнок'),
      primary: true,
      render: item => (
        <div className="min-w-0">
          <Link to={`/children/${item.child_id}`} className="font-semibold text-ink hover:text-brand-600">{item.name}</Link>
          <p className="text-xs text-ink-muted">{[item.branch, item.direction, item.subscription].filter(Boolean).join(' · ')}</p>
          {item.parent && <p className="text-xs text-ink-subtle">{item.parent}</p>}
        </div>
      ),
    },
    { key: 'ends_on', header: t('Абонемент закончился'), mobileAside: true, render: item => formatDate(item.ends_on) },
    {
      key: 'state',
      header: t('Ребёнок сейчас'),
      render: item => {
        const state = CHILD_STATES[item.child_state] || CHILD_STATES.departed
        return <Badge tone={state.tone}>{state.label()}</Badge>
      },
    },
    { key: 'actions', header: '', render: item => <ContactActions item={item} /> },
  ]
  return (
    <>
      <p className="px-5 pb-3 text-[13px] text-ink-muted">
        {t('Абонемент закончился в периоде, продления за {days} дней нет — как в отчёте «Продления». «Ходит дальше» — у ребёнка идёт абонемент другого направления.', { days: graceDays })}
      </p>
      <DataTable
        columns={columns}
        rows={items}
        rowKey={item => item.id}
        empty={<p className="py-8 text-center text-sm text-ink-muted">{t('Непродлённых абонементов за период нет')}</p>}
      />
    </>
  )
}

function rowLabel(dimension, row) {
  if (dimension === 'lifetime') return LIFETIME_LABELS[row.key]?.() || row.label
  if (dimension === 'reason') {
    if (row.key == null) return t('Не отмечен ушедшим')
    if (row.key === '') return t('Причина не указана')
    return row.label
  }
  if (row.key == null) {
    if (dimension === 'group') return t('Без группы')
    if (dimension === 'teacher') return t('Без преподавателя')
    return t('Не указано')
  }
  return row.label
}

function BreakdownTable({ dimension, rows }) {
  const columns = [
    { key: 'label', header: DIMENSIONS.find(d => d.key === dimension).label, primary: true, render: row => rowLabel(dimension, row) },
    { key: 'departed', header: t('Ушли'), align: 'right', mobileAside: true, render: row => formatValue(row.departed, 'count') },
    { key: 'share', header: t('Доля'), align: 'right', render: row => formatValue(row.share, 'percent') },
    { key: 'returned', header: t('Уже вернулись'), align: 'right', render: row => formatValue(row.returned, 'count') },
    { key: 'lifetime', header: t('Средний срок жизни'), align: 'right', render: row => (row.average_lifetime_months == null ? '—' : t('{n} мес.', { n: formatValue(row.average_lifetime_months, 'count') })) },
  ]
  if (dimension === 'group' || dimension === 'teacher') {
    columns.push({
      key: 'context',
      header: t('Группы'),
      render: row => (row.context?.groups.length
        ? <span className="text-xs text-ink-muted">{row.context.groups.map(group => group.name).join(', ')}</span>
        : <span className="text-ink-subtle">—</span>),
    })
  }
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={row => row.key ?? 'none'}
      empty={<p className="py-8 text-center text-sm text-ink-muted">{t('За этот период никто не ушёл')}</p>}
    />
  )
}

function formatMonth(iso) {
  const [y, m] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric' }).format(new Date(y, m - 1, 1))
}
