// Каркас отчётов (TRU-113): отчёт M3 собирается из этих частей, а не рисует
// свой выбор периода, плитки и графики. Примеры всех состояний — /analytics/kit.
export { useAnalyticsFilters, PERIODS } from './filters'
export { useMetrics, useAnalyticsCatalog, useBreakdown, useHeatmap } from './useMetrics'
export { AnalyticsToolbar, PeriodPicker, BranchPicker } from './Toolbar'
export { MetricTile, Change } from './MetricTile'
export { ChartCard, NotEnoughData } from './ChartCard'
export { TrendChart, BarsChart, ComboChart, DonutChart } from './Charts'
export { GaugeChart, HeatmapChart, RankBars } from './Visuals'
export { FunnelChart } from './FunnelChart'
export { formatValue, formatAxis, formatBucket, formatRange } from './format'
export { METRIC_META, PALETTE, REPORTS, metricLabel, breakdownLabel } from './meta'
export { AnalyticsNav } from './Nav'
