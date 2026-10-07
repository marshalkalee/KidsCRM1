import { useEffect, useState } from 'react'
import { Sparkles } from 'lucide-react'
import api from '../../api/axios'
import { Card, ErrorState, Skeleton, cn, money } from '../../ui'
import { locale, plural, t } from '../../i18n'
import { useAI } from './ai'

/** '2026-10' → «октябрь» на языке интерфейса. */
function monthName(month) {
  const [year, number] = month.split('-').map(Number)
  return new Date(year, number - 1, 15).toLocaleString(locale, { month: 'long' })
}

/** '2026-11-01' → «1 ноября» (без сдвига часового пояса). */
function dayMonth(iso) {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleString(locale, { day: 'numeric', month: 'long' })
}

/**
 * Расход ИИ за месяц (TRU-160) — для владельца на странице «Организация».
 * Помощник — платная опция: видно, сколько потрачено из лимита, на что и
 * когда лимит обновится. Без опции карточки нет.
 */
export default function AIUsageCard() {
  const ai = useAI()
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)

  const load = () => api.get('ai/usage/').then(res => setData(res.data)).catch(() => setError(true))
  useEffect(() => { if (ai.enabled) load() }, [ai.enabled])

  if (!ai.enabled) return null
  if (error) return <Card><ErrorState onRetry={() => { setError(false); load() }} /></Card>
  if (!data) return <Skeleton className="h-48" />

  const percent = data.limit_kzt ? Math.min(100, Math.round((100 * data.spent_kzt) / data.limit_kzt)) : 0
  const resets = dayMonth(data.resets_at)

  return (
    <Card>
      <div className="mb-4 flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#ede9fe,#fce7f3)] text-[#7c3aed]">
          <Sparkles className="size-[18px]" />
        </span>
        <div className="min-w-0">
          <h2 className="text-[15px] font-bold text-ink">{t('ИИ-помощник: расход за {month}', { month: monthName(data.month) })}</h2>
          <p className="mt-0.5 text-[13px] text-ink-muted">{t('Лимит обновится {date}.', { date: resets })}</p>
        </div>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-2xl font-bold text-ink">{money(data.spent_kzt)}</span>
        <span className="text-sm text-ink-muted">{t('из {limit}', { limit: money(data.limit_kzt) })}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-muted" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div
          className={cn('h-full rounded-full', data.exhausted ? 'bg-danger-600' : percent >= 80 ? 'bg-warning-600' : 'bg-[#8b5cf6]')}
          style={{ width: `${percent}%` }}
        />
      </div>
      {data.exhausted && (
        <p className="mt-3 rounded-lg bg-danger-50 px-3 py-2 text-[13px] text-danger-700">
          {t('Лимит месяца исчерпан: ИИ-функции вернутся {date}. Чтобы поднять лимит, напишите нам.', { date: resets })}
        </p>
      )}

      {data.by_feature.length === 0 ? (
        <p className="mt-4 text-[13px] text-ink-muted">{t('В этом месяце ИИ ещё не использовали.')}</p>
      ) : (
        <ul className="mt-4 divide-y divide-line">
          {data.by_feature.map(row => (
            <li key={row.key} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink">{t(row.label)}</p>
                <p className="text-xs text-ink-muted">{row.calls} {plural(row.calls, ['запрос', 'запроса', 'запросов'])}</p>
              </div>
              <span className="text-sm font-semibold text-ink">{money(row.cost_kzt)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
