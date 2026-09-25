import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { Card, EmptyState, ErrorState, Skeleton } from './Surface'
import { cn } from './cn'
import { t } from '../i18n'

/**
 * Таблица списка (дети, родители, группы…) на десктопе и карточки на
 * телефоне — без горизонтального скролла (ТЗ п. 10.4).
 *
 * columns: [{ key, header, render?(row), sortable?, align?, className?,
 *             primary?  — главная колонка: заголовок карточки на телефоне,
 *             mobileAside? — на телефоне справа от заголовка (например статус),
 *             mobileRender?(row) — своя отрисовка для карточки; null — поле
 *               в карточке не показывается (пустой долг и т.п.),
 *             hideOnMobile? }]
 * sort: { key, dir: 'asc'|'desc' } + onSortChange(next) — сортировка на сервере.
 * pagination: { page, pageSize, total } + onPageChange(page).
 */
export function DataTable({
  columns, rows, rowKey = row => row.id, loading, error, onRetry,
  sort, onSortChange, pagination, onPageChange, onRowClick, empty,
}) {
  const primary = columns.find(c => c.primary) || columns[0]
  const aside = columns.find(c => c.mobileAside)
  const secondary = columns.filter(c => c !== primary && c !== aside && !c.hideOnMobile)
  const mobileCell = (col, row) => (col.mobileRender ? col.mobileRender(row) : cell(col, row))
  const cell = (col, row) => (col.render ? col.render(row) : (row[col.key] ?? '—'))

  function toggleSort(col) {
    if (!col.sortable || !onSortChange) return
    const dir = sort?.key === col.key && sort.dir === 'asc' ? 'desc' : 'asc'
    onSortChange({ key: col.key, dir })
  }

  let body
  if (error) {
    body = <ErrorState onRetry={onRetry} />
  } else if (loading && !rows?.length) {
    body = (
      <div className="space-y-3 p-5">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-9" />)}
      </div>
    )
  } else if (!rows?.length) {
    body = empty || <EmptyState title={t('Ничего не найдено')} description={t('Измените фильтры или добавьте запись.')} />
  } else {
    body = (
      <>
        {/* Десктоп */}
        {/* Прокрутка внутри карточки: на казахском/английском подписи длиннее. */}
        <div className="hidden overflow-x-auto md:block">
        <table className={cn('w-full text-sm', loading && 'opacity-60')}>
          <thead>
            <tr className="border-b border-line">
              {columns.map(col => {
                const active = sort?.key === col.key
                const SortIcon = active ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown
                return (
                  <th
                    key={col.key}
                    scope="col"
                    className={cn(
                      'px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-ink-subtle',
                      col.align === 'right' && 'text-right',
                      col.className,
                    )}
                    aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                  >
                    {col.sortable && onSortChange ? (
                      <button type="button" onClick={() => toggleSort(col)} className={cn('inline-flex items-center gap-1 uppercase hover:text-ink', active && 'text-ink')}>
                        {col.header}
                        <SortIcon className="size-3.5" />
                      </button>
                    ) : col.header}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn('border-b border-line last:border-0', onRowClick && 'cursor-pointer hover:bg-brand-50/40')}
              >
                {columns.map(col => (
                  <td key={col.key} className={cn('px-4 py-3 align-middle text-ink', col.align === 'right' && 'text-right', col.className)}>
                    {cell(col, row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        </div>

        {/* Телефон */}
        <ul className={cn('divide-y divide-line md:hidden', loading && 'opacity-60')}>
          {rows.map(row => (
            <li
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn('px-4 py-3.5', onRowClick && 'cursor-pointer active:bg-surface-muted')}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 font-semibold text-ink">{cell(primary, row)}</div>
                {aside && <div className="shrink-0">{cell(aside, row)}</div>}
              </div>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px]">
                {secondary.map(col => {
                  const value = mobileCell(col, row)
                  if (value === null) return null
                  return (
                    <div key={col.key} className="min-w-0">
                      <dt className="text-ink-subtle">{col.header}</dt>
                      <dd className="truncate text-ink">{value}</dd>
                    </div>
                  )
                })}
              </dl>
            </li>
          ))}
        </ul>
      </>
    )
  }

  return (
    <Card padded={false} className="overflow-hidden">
      {body}
      {pagination && pagination.total > pagination.pageSize && (
        <Pagination {...pagination} onPageChange={onPageChange} />
      )}
    </Card>
  )
}

function Pagination({ page, pageSize, total, onPageChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 text-[13px] text-ink-muted">
      <span>{from}–{to} {t('из')} {total}</span>
      <div className="flex items-center gap-1">
        <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)} className="rounded-md p-1.5 hover:bg-surface-muted disabled:opacity-40" aria-label={t('Предыдущая страница')}>
          <ChevronLeft className="size-4" />
        </button>
        <span className="px-2 font-semibold text-ink">{page} / {pages}</span>
        <button type="button" disabled={page >= pages} onClick={() => onPageChange(page + 1)} className="rounded-md p-1.5 hover:bg-surface-muted disabled:opacity-40" aria-label={t('Следующая страница')}>
          <ChevronRight className="size-4" />
        </button>
      </div>
    </div>
  )
}
