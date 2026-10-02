import { useCallback, useEffect, useState } from 'react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'

/**
 * Метрики отчёта одним запросом (TRU-113 поверх API TRU-118):
 *   const { data, loading, error, reload } = useMetrics(['revenue', 'visits'], filters)
 * data.metrics[имя] — { value, previous, change_percent, series, enough_data,
 * days_until_enough, unit, label }. Смена периода, филиалов или филиала в
 * шапке — новый запрос; старый отменяется.
 */
export function useMetrics(names, filters, { series = true, compare = true } = {}) {
  const { activeBranchId } = useSession()
  const [state, setState] = useState({ key: null, data: null, error: null })
  const [reloadKey, setReloadKey] = useState(0)
  const namesKey = names.join(',')
  const key = `${namesKey}|${filters.query}|${activeBranchId}|${series}|${compare}|${reloadKey}`

  useEffect(() => {
    if (!filters.ready || !namesKey) return undefined
    const controller = new AbortController()
    const params = new URLSearchParams(filters.query)
    params.set('metrics', namesKey)
    if (!series) params.set('series', '0')
    if (!compare) params.set('compare', '0')
    api.get(`analytics/metrics/?${params}`, { signal: controller.signal })
      .then(res => setState({ key, data: res.data, error: null }))
      .catch(err => {
        if (err.name !== 'CanceledError') setState(prev => ({ ...prev, key, error: err }))
      })
    return () => controller.abort()
  }, [key, namesKey, filters.query, filters.ready, series, compare])

  const reload = useCallback(() => setReloadKey(k => k + 1), [])
  return {
    data: state.data,
    // Пока новый запрос в пути, показываем прошлые цифры приглушённо, а не мигаем скелетоном.
    loading: filters.ready && state.key !== key,
    error: state.key === key ? state.error : null,
    reload,
  }
}

/** Справочник для панели фильтров: метрики, доступные филиалы, периоды. */
export function useAnalyticsCatalog() {
  const [catalog, setCatalog] = useState(null)
  useEffect(() => {
    api.get('analytics/catalog/').then(res => setCatalog(res.data)).catch(() => setCatalog({ branches: [], metrics: [] }))
  }, [])
  return catalog
}

/**
 * Разбивка метрики по измерению и тепловая карта — тот же период и филиалы:
 *   useBreakdown('revenue', 'method', filters) → { data: { items, unit }, loading, error }
 *   useHeatmap(filters) → { data: { cells } }
 */
export function useAnalyticsGet(path, extra, filters) {
  const { activeBranchId } = useSession()
  const [state, setState] = useState({ key: null, data: null, error: null })
  const [reloadKey, setReloadKey] = useState(0)
  const key = `${path}|${extra}|${filters.query}|${activeBranchId}|${reloadKey}`
  useEffect(() => {
    // Пустой path — «не грузить» (например, отчёт закрыт тарифом).
    if (!filters.ready || !path) return undefined
    const controller = new AbortController()
    const params = new URLSearchParams(filters.query)
    new URLSearchParams(extra).forEach((value, name) => params.set(name, value))
    api.get(`analytics/${path}/?${params}`, { signal: controller.signal })
      .then(res => setState({ key, data: res.data, error: null }))
      .catch(err => {
        if (err.name !== 'CanceledError') setState(prev => ({ ...prev, key, error: err }))
      })
    return () => controller.abort()
  }, [key, path, extra, filters.query, filters.ready])
  const reload = useCallback(() => setReloadKey(value => value + 1), [])
  return { data: state.data, loading: Boolean(path) && filters.ready && state.key !== key, error: state.key === key ? state.error : null, reload }
}

export function useBreakdown(metric, by, filters) {
  return useAnalyticsGet('breakdown', `metric=${metric}&by=${by}`, filters)
}

export function useHeatmap(filters) {
  return useAnalyticsGet('heatmap', '', filters)
}
