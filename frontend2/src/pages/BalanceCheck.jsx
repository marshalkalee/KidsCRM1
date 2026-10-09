import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import api from '../api/axios'
import { Card, EmptyState, ErrorState, PageHeader, Skeleton, formatDateTime } from '../ui'
import { t } from '../i18n'

/*
 * Сверка остатков занятий (TRU-61, критерий приёмки MVP № 3; TRU-152).
 * Каждую ночь система пересчитывает остаток каждого абонемента по журналу
 * списаний. Разошёлся с сохранённым — остаток сразу исправляется, а строка
 * остаётся здесь. Пустой отчёт за две недели — и есть «расхождений нет».
 */
export default function BalanceCheck() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(false)
  const load = useCallback(() => {
    api.get('subscriptions/discrepancies/')
      .then(res => { setRows(res.data); setError(false) })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!rows) return <Skeleton className="h-64" />

  return (
    <div>
      <PageHeader description={t('Каждую ночь система пересчитывает остаток занятий каждого абонемента по журналу списаний. Если сохранённый остаток разошёлся с пересчётом, он сразу исправляется, а случай записывается сюда.')} />
      <Card padded={false}>
        {rows.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title={t('Расхождений нет')}
            description={t('Остатки занятий совпадают с журналом списаний. Для приёмки: две недели без строк здесь и сверка нескольких абонементов с ручным подсчётом администратора.')}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead>
                <tr className="text-left text-[12px] text-ink-muted">
                  <th className="px-5 py-3 font-semibold">{t('Когда найдено')}</th>
                  <th className="px-2 py-3 font-semibold">{t('Ребёнок')}</th>
                  <th className="px-2 py-3 font-semibold">{t('Абонемент')}</th>
                  <th className="px-5 py-3 text-right font-semibold">{t('Было → стало')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map(row => (
                  <tr key={row.id}>
                    <td className="whitespace-nowrap px-5 py-2.5 text-ink-muted">{formatDateTime(row.found_at)}</td>
                    <td className="px-2 py-2.5"><Link to={`/children/${row.child_id}`} className="font-semibold text-ink hover:text-brand-600">{row.child_name}</Link></td>
                    <td className="px-2 py-2.5 text-ink">{row.subscription_name}</td>
                    <td className="whitespace-nowrap px-5 py-2.5 text-right font-semibold text-ink">{row.cached_value ?? '—'} → {row.recomputed_value ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {rows.length > 0 && (
        <p className="mt-2 text-[13px] text-ink-muted">{t('Если строки появляются регулярно — это ошибка в системе, а не случайность: сообщите разработчикам.')}</p>
      )}
    </div>
  )
}
