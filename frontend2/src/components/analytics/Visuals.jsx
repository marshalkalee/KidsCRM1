import { Fragment } from 'react'
import { cn } from '../../ui'
import { t } from '../../i18n'
import { formatValue } from './format'
import { PALETTE, breakdownLabel } from './meta'

/**
 * Не-осевые визуализации отчётов (TRU-113): шкала, тепловая карта,
 * рейтинг. Своя разметка вместо recharts — так они одинаково читаются на
 * телефоне и не зависят от размеров контейнера.
 */

/**
 * Полукруглая шкала 0–100%: заполняемость, выполнение плана. threshold —
 * отметка порога (например «недозаполнена ниже 50%» из настроек центра).
 */
export function GaugeChart({ value, threshold, label }) {
  const percent = Math.max(0, Math.min(100, Number(value) || 0))
  const below = threshold != null && percent < threshold
  const color = below ? 'var(--color-warning-600)' : 'var(--color-success-600)'
  const R = 80
  const arc = Math.PI * R
  const point = p => {
    const angle = Math.PI * (1 - p / 100)
    return [100 + R * Math.cos(angle), 100 - R * Math.sin(angle)]
  }
  const [tx, ty] = threshold != null ? point(threshold) : [0, 0]
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 116" className="w-full max-w-[260px]" role="img" aria-label={`${label}: ${formatValue(percent, 'percent')}`}>
        <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="var(--color-surface-muted)" strokeWidth="16" strokeLinecap="round" />
        <path
          d="M 20 100 A 80 80 0 0 1 180 100"
          fill="none"
          stroke={color}
          strokeWidth="16"
          strokeLinecap="round"
          strokeDasharray={`${(arc * percent) / 100} ${arc}`}
        />
        {threshold != null && (
          <line x1={tx} y1={ty} x2={100 + (tx - 100) * 0.72} y2={100 + (ty - 100) * 0.72} stroke="var(--color-ink)" strokeWidth="2" />
        )}
        <text x="100" y="92" textAnchor="middle" className="fill-ink" style={{ fontSize: 28, fontWeight: 700 }}>
          {formatValue(percent, 'percent')}
        </text>
      </svg>
      {threshold != null && (
        <p className={cn('mt-1 text-center text-xs', below ? 'text-warning-600' : 'text-ink-subtle')}>
          {below
            ? t('Ниже порога {threshold}% — группы недобраны', { threshold })
            : t('Порог недозаполненности — {threshold}%', { threshold })}
        </p>
      )}
    </div>
  )
}

const WEEKDAYS = () => [t('Пн'), t('Вт'), t('Ср'), t('Чт'), t('Пт'), t('Сб'), t('Вс')]

/**
 * Тепловая карта «день недели × час»: где пик, а где пустые залы.
 * cells — [{weekday: 1–7, hour: 0–23, value}]. Часы — от первого до
 * последнего занятия, без пустых ночных колонок.
 */
export function HeatmapChart({ cells, unitLabel = t('посещений') }) {
  const hours = cells.map(c => c.hour)
  const first = Math.min(...hours)
  const last = Math.max(...hours)
  const columns = Array.from({ length: last - first + 1 }, (_, i) => first + i)
  const max = Math.max(...cells.map(c => c.value), 1)
  const at = (weekday, hour) => cells.find(c => c.weekday === weekday && c.hour === hour)?.value || 0
  const peak = cells.reduce((best, c) => (c.value > (best?.value || 0) ? c : best), null)
  const days = WEEKDAYS()
  return (
    <div>
      <div className="overflow-x-auto">
        <div
          className="grid gap-1"
          style={{ gridTemplateColumns: `2rem repeat(${columns.length}, minmax(1.25rem, 1fr))` }}
        >
          <span />
          {columns.map(hour => (
            <span key={hour} className="text-center text-[10px] text-ink-subtle">{hour}:00</span>
          ))}
          {days.map((day, index) => (
            <Fragment key={day}>
              <span className="flex items-center text-[11px] font-semibold text-ink-muted">{day}</span>
              {columns.map(hour => {
                const value = at(index + 1, hour)
                const share = value / max
                return (
                  <span
                    key={hour}
                    title={`${day}, ${hour}:00 — ${formatValue(value, 'count')} ${unitLabel}`}
                    className="h-6 rounded-[5px] sm:h-7"
                    style={{
                      background: value ? PALETTE[0] : 'var(--color-surface-muted)',
                      opacity: value ? 0.15 + share * 0.85 : 1,
                    }}
                  />
                )
              })}
            </Fragment>
          ))}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-subtle">
        {peak && <p>{t('Пик — {day}, {hour}:00', { day: days[peak.weekday - 1], hour: peak.hour })}</p>}
        <p className="flex items-center gap-1.5">
          {t('меньше')}
          {[0.2, 0.45, 0.7, 1].map(o => <span key={o} className="size-3 rounded-[3px]" style={{ background: PALETTE[0], opacity: o }} />)}
          {t('больше')}
        </p>
      </div>
    </div>
  )
}

/**
 * Рейтинг — горизонтальные полосы от большего к меньшему с долей от
 * итога: выручка по филиалам, заявки по источникам.
 */
export function RankBars({ items, unit, color = PALETTE[0], limit = 8, showShare = true, max: fixedMax }) {
  const rows = (items || []).slice(0, limit).map(item => ({ ...item, value: Number(item.value) }))
  const total = (items || []).reduce((sum, item) => sum + Number(item.value), 0)
  // Для процентов шкала — до 100, а не до лучшего: 60% не должно выглядеть «полной» полосой.
  const max = fixedMax ?? Math.max(...rows.map(r => r.value), 1)
  return (
    <ol className="space-y-3">
      {rows.map((row, index) => (
        <li key={row.key ?? 'none'}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
            <span className="min-w-0 truncate text-ink">
              <span className="mr-2 text-ink-subtle">{index + 1}</span>
              {breakdownLabel(row)}
            </span>
            <span className="shrink-0 font-semibold text-ink">
              {formatValue(row.value, unit)}
              {showShare && <span className="ml-1.5 text-xs font-normal text-ink-subtle">{total ? Math.round((row.value / total) * 100) : 0}%</span>}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
            <div className="h-full rounded-full" style={{ width: `${(row.value / max) * 100}%`, background: color }} />
          </div>
        </li>
      ))}
    </ol>
  )
}
