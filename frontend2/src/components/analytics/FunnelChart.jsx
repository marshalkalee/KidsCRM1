import { ChevronRight } from 'lucide-react'
import { t } from '../../i18n'
import { formatValue } from './format'
import { PALETTE } from './meta'

/**
 * Воронка (TRU-113, конверсия TRU-115): этапы сверху вниз, ширина — доля
 * от первого этапа, между этапами — конверсия шага. На телефоне читается
 * так же — это не график, а полосы.
 *
 * stages: [{ label, value, step?, current? }]. step — своя конверсия шага
 * (например «пришёл → купил» только среди пришедших), иначе value/предыдущий.
 * onSelect(stage) — клик по «сейчас на этапе: N» (список застрявших).
 */
export function FunnelChart({ stages, onSelect }) {
  const first = Number(stages[0]?.value) || 0
  return (
    <ol className="flex flex-col gap-1.5">
      {stages.map((stage, index) => {
        const value = Number(stage.value) || 0
        const share = first ? value / first : 0
        const previous = index ? Number(stages[index - 1].value) || 0 : null
        const step = stage.step ?? (previous ? Math.round((value / previous) * 100) : null)
        return (
          <li key={stage.key || stage.label}>
            {index > 0 && (
              <p className="py-0.5 pl-1 text-[11px] text-ink-subtle">
                ↓ {step == null ? '—' : t('{percent}% перешли дальше', { percent: step })}
              </p>
            )}
            <div className="flex items-center gap-3">
              <div className="relative h-9 min-w-0 flex-1 overflow-hidden rounded-md bg-surface-muted">
                <div
                  className="absolute inset-y-0 left-0 rounded-md"
                  style={{ width: `${Math.max(share * 100, value ? 2 : 0)}%`, background: PALETTE[0], opacity: 1 - index * 0.12 }}
                />
                <span className="relative flex h-full items-center truncate px-3 text-[13px] font-semibold text-ink">{stage.label}</span>
              </div>
              <div className="w-24 shrink-0 text-right">
                <p className="text-sm font-bold text-ink">{formatValue(value, 'count')}</p>
                <p className="text-[11px] text-ink-subtle">{first ? `${Math.round(share * 100)}%` : '—'}</p>
              </div>
            </div>
            {onSelect && stage.current > 0 && (
              <button
                type="button"
                onClick={() => onSelect(stage)}
                className="mt-0.5 inline-flex items-center gap-0.5 pl-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700"
              >
                {t('сейчас на этапе: {n}', { n: stage.current })}
                <ChevronRight className="size-3" />
              </button>
            )}
          </li>
        )
      })}
    </ol>
  )
}
