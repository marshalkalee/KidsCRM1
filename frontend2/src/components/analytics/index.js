// Каркас отчётов (TRU-113): отчёт M3 собирается из этих частей, а не рисует
// свой выбор периода, плитки и графики. Примеры всех состояний — /analytics/kit.
export { useAnalyticsFilters, PERIODS } from './filters'
export { useMetrics, useAnalyticsCatalog } from './useMetrics'
export { AnalyticsToolbar, PeriodPicker, BranchPicker } from './Toolbar'
export { MetricTile, Change } from './MetricTile'
export { ChartCard, NotEnoughData } from './ChartCard'
export { TrendChart, BarsChart } from './Charts'
export { FunnelChart } from './FunnelChart'
export { formatValue, formatAxis, formatBucket, formatRange } from './format'
export { METRIC_META, PALETTE, metricLabel } from './meta'
