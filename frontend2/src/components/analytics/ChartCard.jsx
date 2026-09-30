import { BarChart3, Hourglass } from 'lucide-react'
import { Card, CardHeader, EmptyState, ErrorState, Skeleton } from '../../ui'
import { t } from '../../i18n'
import { daysLabel } from './format'

/**
 * Карточка графика с общими состояниями (TRU-113) — отчёт не рисует их сам:
 * - загрузка — скелетон той же высоты, страница не прыгает;
 * - ошибка — «Повторить»;
 * - данных мало — объяснение и сколько ещё ждать, график не показываем:
 *   по двум точкам владелец сделает неверный вывод;
 * - за период пусто — «нет данных», а не пустые оси.
 *
 * metric — метрика из API (для enough_data / series); children — сам график.
 * Для разбивки: ready — пришли ли её данные, empty — пусто ли в ней.
 */
export function ChartCard({ title, description, actions, metric, loading, error, onRetry, height = 260, ready = true, empty, autoHeight = false, className, children }) {
  let body
  if (error) body = <ErrorState onRetry={onRetry} />
  else if (!metric || !ready) body = <div style={{ height }}><Skeleton className="h-full w-full" /></div>
  else if (!metric.enough_data) body = <NotEnoughData metric={metric} height={height} />
  else if (empty ?? isEmpty(metric)) body = <EmptyChart height={height} />
  else if (empty === undefined && metric.series && metric.series.filter(p => p.value != null).length < 2) body = <FewPoints height={height} />
  // autoHeight — для разметки без осей (рейтинг, кольцо, тепловая карта): растёт по содержимому.
  else body = <div className={loading ? 'opacity-60 transition-opacity' : undefined} style={autoHeight ? { minHeight: height } : { height }}>{children}</div>
  return (
    <Card className={className}>
      <CardHeader title={title} description={description} actions={actions} />
      {body}
    </Card>
  )
}

function isEmpty(metric) {
  if (!metric.series) return metric.value == null
  return metric.series.every(point => point.value == null || Number(point.value) === 0)
}

export function NotEnoughData({ metric, height }) {
  const since = metric.data_since
  return (
    <div style={{ minHeight: height }} className="flex items-center justify-center">
      <EmptyState
        icon={Hourglass}
        title={since ? t('Данных пока мало') : t('Данных ещё нет')}
        description={since
          ? t('Отчёт станет точным через {days}: по паре недель легко сделать неверный вывод.', { days: daysLabel(metric.days_until_enough) })
          : t('Цифры появятся, когда в системе начнут вести эти записи.')}
        className="py-6"
      />
    </div>
  )
}

// У снимков (долг, заполняемость) история копится с выката — первые дни
// точка одна, линию из неё не построить.
function FewPoints({ height }) {
  return (
    <div style={{ minHeight: height }} className="flex items-center justify-center">
      <EmptyState icon={Hourglass} title={t('История только начала копиться')} description={t('График появится, когда накопится хотя бы два дня.')} className="py-6" />
    </div>
  )
}

function EmptyChart({ height }) {
  return (
    <div style={{ minHeight: height }} className="flex items-center justify-center">
      <EmptyState icon={BarChart3} title={t('За этот период данных нет')} description={t('Выберите другой период или филиал.')} className="py-6" />
    </div>
  )
}
