import { useCallback, useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { t } from '../../i18n'

/**
 * Период и филиалы отчётов (TRU-113). Живут в адресе страницы —
 * ссылкой на отчёт можно поделиться, а при переходе между отчётами
 * выбор сохраняется: последний выбор помнится в sessionStorage и
 * подставляется, если в адресе ничего нет.
 *
 * Филиалы: ?branch=<id>&branch=<id>. Нет параметра — как в шапке
 * (X-Branch-Id уходит сам), нет филиала в шапке — все доступные.
 */
export const PERIODS = [
  { value: 'today', get label() { return t('Сегодня') } },
  { value: 'week', get label() { return t('Неделя') } },
  { value: 'month', get label() { return t('Месяц') } },
  { value: 'quarter', get label() { return t('Квартал') } },
  { value: 'year', get label() { return t('Год') } },
  { value: 'custom', get label() { return t('Период') } },
]

const KEYS = ['period', 'from', 'to', 'branch']
const STORAGE_KEY = 'analytics:filters'

function remember(params) {
  try {
    const kept = new URLSearchParams()
    KEYS.forEach(key => params.getAll(key).forEach(value => kept.append(key, value)))
    sessionStorage.setItem(STORAGE_KEY, kept.toString())
  } catch { /* приватный режим — просто не помним */ }
}

function remembered() {
  try {
    return new URLSearchParams(sessionStorage.getItem(STORAGE_KEY) || '')
  } catch {
    return new URLSearchParams()
  }
}

export function useAnalyticsFilters() {
  const [params, setParams] = useSearchParams()

  // Пришли в отчёт без фильтров в адресе — вернуть последний выбор.
  useEffect(() => {
    if (KEYS.some(key => params.has(key))) return
    const saved = remembered()
    if ([...saved.keys()].length) {
      setParams(current => {
        const next = new URLSearchParams(current)
        saved.forEach((value, key) => next.append(key, value))
        return next
      }, { replace: true })
    }
  }, [params, setParams])

  const period = params.get('period') || 'month'
  const from = params.get('from') || ''
  const to = params.get('to') || ''
  const branchKey = params.getAll('branch').join(',')
  const branches = useMemo(() => (branchKey ? branchKey.split(',') : []), [branchKey])

  const update = useCallback(changes => {
    setParams(current => {
      const next = new URLSearchParams(current)
      Object.entries(changes).forEach(([key, value]) => {
        next.delete(key)
        const values = Array.isArray(value) ? value : [value]
        values.filter(v => v !== '' && v != null).forEach(v => next.append(key, v))
      })
      remember(next)
      return next
    }, { replace: true })
  }, [setParams])

  const setPeriod = useCallback(value => {
    update(value === 'custom' ? { period: value } : { period: value, from: '', to: '' })
  }, [update])
  const setRange = useCallback((start, end) => update({ period: 'custom', from: start, to: end }), [update])
  const setBranches = useCallback(ids => update({ branch: ids }), [update])

  // Свой период без обеих дат ещё не выбран — запрашивать рано.
  const ready = period !== 'custom' || Boolean(from && to)
  const query = useMemo(() => {
    const q = new URLSearchParams({ period })
    if (period === 'custom') { q.set('from', from); q.set('to', to) }
    branches.forEach(id => q.append('branch', id))
    return q.toString()
  }, [period, from, to, branches])

  return { period, from, to, branches, ready, query, setPeriod, setRange, setBranches }
}
