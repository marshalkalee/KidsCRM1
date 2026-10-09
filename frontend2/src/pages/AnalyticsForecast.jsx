import { CalendarClock, HandCoins, Info, Wallet } from 'lucide-react'
import { Badge, Card, CardHeader, DataTable, ErrorState, PageHeader, Skeleton, cn } from '../ui'
import { locale, t } from '../i18n'
import {
  AnalyticsNav, BranchPicker, ExportButton, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'

/**
 * «Прогноз» (TRU-125, ТЗ раздел 7): единственный отчёт, смотрящий вперёд.
 * Три разные величины — три отдельные карточки, без общей суммы:
 * оплачено, но не отработано (обязательство центра); продано, но не
 * оплачено (долг); ожидаемые продления следующего месяца (расчёт —
 * analytics/forecast.py). Пока данных
 * мало, прогноз не показываем или показываем только диапазон — цифра
 * из воздуха хуже, чем никакой. Ниже — проверка прогноза на прошлых месяцах.
 * Считается от сегодня, поэтому период не выбирается, только филиалы.
 */
export default function AnalyticsForecast() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const { data, error, loading } = useAnalyticsGet('forecast', '', filters)

  return (
    <>
      <PageHeader
        title={t('Аналитика')}
        description={t('Сколько денег уже получено, сколько должно прийти и чего ждать от продлений')}
        actions={<ExportButton report="forecast" filters={filters} />}
      />
      <AnalyticsNav />
      <div className="mb-5 flex flex-col gap-3 rounded-xl border border-line bg-surface px-4 py-3 sm:px-5 lg:flex-row lg:items-center lg:justify-between">
        <p className="text-[13px] text-ink-muted">
          {data
            ? t('Считается на сегодня ({date}), период на прогноз не влияет.', { date: formatDay(data.today) })
            : t('Считается на сегодня. Период на прогноз не влияет.')}
        </p>
        <BranchPicker filters={filters} catalog={catalog} />
      </div>

      {error ? (
        <Card><ErrorState /></Card>
      ) : !data ? (
        <Skeleton className="h-96" />
      ) : (
        <div className={cn('transition-opacity', loading && 'opacity-60')}>
          <div className="mb-4 grid gap-4 lg:grid-cols-3">
            <ValueCard
              icon={Wallet}
              tone="info"
              title={t('Оплачено, но не отработано')}
              value={formatValue(data.prepaid.value, 'money')}
              hint={t('Деньги уже в кассе, занятия впереди. Это обязательство центра перед родителями, а не будущая выручка.')}
              footer={t('{n} абонементов', { n: data.prepaid.subscriptions })}
            />
            <ValueCard
              icon={HandCoins}
              tone="warning"
              title={t('Продано, но не оплачено')}
              value={formatValue(data.unpaid.value, 'money')}
              hint={t('Задолженность: эти деньги должны прийти от родителей. Та же сумма, что на экране «Задолженности».')}
              footer={t('{n} абонементов', { n: data.unpaid.subscriptions })}
            />
            <ForecastCard forecast={data.forecast} rules={data.rules} />
          </div>
          <p className="mb-4 flex items-start gap-2 text-[13px] text-ink-muted">
            <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
            {t('Три величины не складываются: это разные деньги. Первая уже получена, вторая продана, третья — только ожидание.')}
          </p>
          <HowCard forecast={data.forecast} rules={data.rules} />
          <RetroCard rows={data.retrospective} />
        </div>
      )}
    </>
  )
}

const TONES = {
  info: 'bg-info-50 text-info-600',
  warning: 'bg-warning-50 text-warning-600',
  brand: 'bg-brand-50 text-brand-700',
}

function ValueCard({ icon: Icon, tone, title, value, hint, footer, badge }) {
  return (
    <Card className="flex flex-col">
      <div className="mb-3 flex items-center gap-2.5">
        <span className={cn('grid size-9 place-items-center rounded-lg', TONES[tone])}><Icon className="size-[18px]" /></span>
        <h2 className="text-[15px] font-bold text-ink">{title}</h2>
        {badge}
      </div>
      <p className="text-2xl font-bold text-ink">{value}</p>
      <p className="mt-2 flex-1 text-[13px] text-ink-muted">{hint}</p>
      {footer && <p className="mt-3 text-xs text-ink-subtle">{footer}</p>}
    </Card>
  )
}

function ForecastCard({ forecast, rules }) {
  const month = formatMonth(forecast.month)
  const sample = forecast.conversion.ended
  const title = t('Ожидаемые продления: {month}', { month })
  const footer = forecast.expected_renewals == null
    ? t('Заканчиваются в этом месяце: {n} абонементов', { n: forecast.expiring })
    : t('Ожидаем продлений: ~{n}', { n: formatValue(Math.round(forecast.expected_renewals), 'count') })
  if (forecast.status === 'hidden') {
    return (
      <ValueCard
        icon={CalendarClock}
        tone="brand"
        title={title}
        value={t('Прогноза пока нет')}
        badge={<Badge tone="warning">{t('мало данных')}</Badge>}
        hint={t('Закончилось {n} абонементов, нужно хотя бы {min}, чтобы понять, как часто продлевают. Цифра из воздуха хуже, чем никакой.', { n: sample, min: rules.min_sample_range })}
        footer={footer}
      />
    )
  }
  const range = `${formatValue(forecast.low, 'money')} – ${formatValue(forecast.high, 'money')}`
  if (forecast.status === 'range') {
    return (
      <ValueCard
        icon={CalendarClock}
        tone="brand"
        title={title}
        value={range}
        badge={<Badge tone="warning">{t('мало данных')}</Badge>}
        hint={t('Только диапазон: по {n} закончившимся абонементам точную цифру назвать нельзя. Точная появится с {min}.', { n: sample, min: rules.min_sample_point })}
        footer={footer}
      />
    )
  }
  return (
    <ValueCard
      icon={CalendarClock}
      tone="brand"
      title={title}
      value={formatValue(forecast.value, 'money')}
      hint={`${t('Если продлевать будут как обычно. Скорее всего {range}. Новые клиенты и оплаты долгов сюда не входят.', { range })}${forecast.calibration_percent == null ? '' : ` ${t('Диапазон учитывает ошибку прогноза на прошлых месяцах (до {p}%).', { p: formatValue(forecast.calibration_percent, 'count') })}`}`}
      footer={footer}
    />
  )
}

function HowCard({ forecast, rules }) {
  const conversion = forecast.conversion
  const month = formatMonth(forecast.month)
  const rows = [
    [t('Активных абонементов в расчёте (ещё не продлены)'), formatValue(forecast.base, 'count')],
    [t('Из них заканчиваются: {month}', { month }), formatValue(forecast.expiring, 'count')],
    [t('Ожидаемых продлений: {month}', { month }), forecast.expected_renewals == null ? '—' : formatValue(forecast.expected_renewals, 'count')],
    [
      t('Конверсия продлений'),
      conversion.ended
        ? t('{rate} — продлили {renewed} из {ended}', { rate: formatValue(conversion.rate, 'percent'), renewed: formatValue(conversion.renewed, 'count'), ended: formatValue(conversion.ended, 'count') })
        : '—',
    ],
    [
      t('Конверсия — диапазон ({p}%)', { p: rules.confidence }),
      conversion.ended ? `${formatValue(conversion.low, 'percent')} – ${formatValue(conversion.high, 'percent')}` : '—',
    ],
    [
      forecast.avg_check_source === 'base' ? t('Средняя цена активных абонементов (продлений в выборке нет)') : t('Средняя цена продления'),
      formatValue(forecast.avg_check, 'money'),
    ],
  ]
  return (
    <Card className="mb-4">
      <CardHeader
        title={t('Как считаем прогноз')}
        description={t('Продления, которые придутся на месяц × средняя цена продления')}
      />
      <dl className="divide-y divide-line text-[13px]">
        {rows.map(([label, value]) => (
          <div key={label} className="flex flex-wrap justify-between gap-2 py-2">
            <dt className="text-ink-muted">{label}</dt>
            <dd className="font-semibold text-ink">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-ink-subtle">
        {t('Выборка — абонементы, закончившиеся с {from} по {to}. Продлён — у ребёнка есть следующий абонемент того же направления (или проданный кнопкой «Продлить»), начавшийся не позже {days} дней после окончания.', {
          from: formatDay(conversion.window_start),
          to: formatDay(conversion.window_end),
          days: rules.grace_days,
        })}
      </p>
      <p className="mt-2 text-xs text-ink-subtle">
        {t('Продление ждём в день окончания абонемента с той же долей, что в прошлые месяцы. Месячный абонемент, который закончится в этом месяце, продлят, и продление тоже может закончиться и продлиться в следующем — так в прогноз попадают абонементы, которые ещё не проданы. Новые клиенты и оплаты долгов не входят.')}
      </p>
    </Card>
  )
}

function RetroCard({ rows }) {
  const columns = [
    { key: 'month', header: t('Месяц'), primary: true, render: row => formatMonth(row.month) },
    {
      key: 'renewals',
      header: t('Продлений: ждали / было'),
      align: 'right',
      render: row => `${row.expected_renewals == null ? '—' : formatValue(row.expected_renewals, 'count')} / ${formatValue(row.fact_renewed, 'count')}`,
    },
    {
      key: 'forecast',
      header: t('Прогноз'),
      align: 'right',
      render: row => (row.status === 'hidden'
        ? <span className="text-ink-subtle">{t('не показали бы')}</span>
        : row.status === 'range'
          ? `${formatValue(row.low, 'money')} – ${formatValue(row.high, 'money')}`
          : formatValue(row.value, 'money')),
    },
    {
      key: 'fact',
      header: t('Факт'),
      align: 'right',
      mobileAside: true,
      render: row => <span className="font-semibold text-ink">{formatValue(row.fact, 'money')}</span>,
    },
    { key: 'deviation', header: t('Отклонение'), align: 'right', render: row => (row.deviation_percent == null ? '—' : `${row.deviation_percent > 0 ? '+' : ''}${formatValue(row.deviation_percent, 'percent')}`) },
    {
      key: 'check',
      header: t('Попали в диапазон'),
      render: row => (
        <span className="flex flex-wrap items-center gap-1.5">
          {row.in_range == null ? '—' : <Badge tone={row.in_range ? 'success' : 'danger'}>{row.in_range ? t('да') : t('нет')}</Badge>}
          {!row.complete && <Badge tone="neutral">{t('факт до {date}', { date: formatDay(row.settles_on) })}</Badge>}
        </span>
      ),
    },
  ]
  return (
    <Card padded={false}>
      <div className="p-5 pb-0">
        <CardHeader
          title={t('Проверка на прошлых месяцах')}
          description={t('Прогноз, каким он был на 1-е число предыдущего месяца, против того, сколько продлили на самом деле')}
        />
      </div>
      <DataTable columns={columns} rows={[...rows].reverse()} rowKey={row => row.month} />
    </Card>
  )
}

function parse(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function formatMonth(iso) {
  return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(parse(iso))
}

function formatDay(iso) {
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' }).format(parse(iso))
}
