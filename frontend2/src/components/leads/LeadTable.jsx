import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, Inbox, Search, X } from 'lucide-react'
import api from '../../api/axios'
import { Avatar, Badge, Button, Checkbox, DataTable, Dropdown, EmptyState, apiErrorMessage, cn, formatDateTime, plural, useToast } from '../../ui'
import { t } from '../../i18n'
import RejectModal from './RejectModal'
import { LEAD_STATUSES, stageBadge } from './format'

const PAGE_SIZE = 50

/**
 * Таблица заявок (TRU-95): те же фильтры, что у доски (из адреса), плюс
 * сортировка, страницы, массовые действия и выгрузка в Excel. На телефоне
 * DataTable сам превращает строки в карточки.
 */
export default function LeadTable({ query, params, update, reloadKey, staff, onCount, onReset, hasFilters, returnTo }) {
  const navigate = useNavigate()
  const toast = useToast()
  const [data, setData] = useState({ key: null, results: [], count: 0, error: false })
  const [selected, setSelected] = useState(() => new Set())
  const [rejecting, setRejecting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [stages, setStages] = useState([])

  useEffect(() => {
    api.get('leads/stages/').then(res => setStages(res.data)).catch(() => {})
  }, [])

  const page = Math.max(1, Number(params.get('page')) || 1)
  const ordering = params.get('ordering') || '-created_at'
  const sort = { key: ordering.replace(/^-/, ''), dir: ordering.startsWith('-') ? 'desc' : 'asc' }
  const key = JSON.stringify({ query, page, ordering, reloadKey, refresh })

  useEffect(() => {
    let alive = true
    api.get('leads/', { params: { ...query, page, ordering } })
      .then(res => { if (alive) { setData({ key, results: res.data.results, count: res.data.count, error: false }); onCount(res.data.count) } })
      .catch(() => { if (alive) setData(d => ({ ...d, key, error: true })) })
    return () => { alive = false }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  // Сменили страницу или фильтры — выбор сбрасывается: иначе легко задеть
  // заявки, которых уже не видно.
  const [selectionKey, setSelectionKey] = useState(key)
  if (selectionKey !== key) {
    setSelectionKey(key)
    setSelected(new Set())
  }

  const loading = data.key !== key
  const rows = data.results
  const allOnPage = rows.length > 0 && rows.every(r => selected.has(r.id))
  const toggle = id => setSelected(s => { const next = new Set(s); if (next.has(id)) next.delete(id); else next.add(id); return next })

  async function bulk(payload) {
    setBusy(true)
    try {
      const res = await api.post('leads/bulk/', { ids: [...selected], ...payload })
      const { updated, failed } = res.data
      if (updated) toast.success(t('Обновлено: {n}', { n: updated }))
      if (failed.length) toast.error(t('Не удалось для {n}: {reason}', { n: failed.length, reason: t(failed[0].error) }))
      setRefresh(r => r + 1)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function exportExcel() {
    try {
      const res = await api.get('leads/export/', { params: { ...query, ordering }, responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const link = Object.assign(document.createElement('a'), { href: url, download: `leads-${new Date().toISOString().slice(0, 10)}.xlsx` })
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const columns = [
    {
      key: 'select',
      header: <Checkbox checked={allOnPage} onChange={() => setSelected(allOnPage ? new Set() : new Set(rows.map(r => r.id)))} aria-label={t('Выбрать все на странице')} />,
      render: row => <span onClick={e => e.stopPropagation()}><Checkbox checked={selected.has(row.id)} onChange={() => toggle(row.id)} aria-label={t('Выбрать')} /></span>,
      mobileRender: () => null,
      className: 'w-10',
    },
    {
      key: 'child_name',
      header: t('Ребёнок'),
      sortable: true,
      primary: true,
      render: row => (
        <span className="flex items-center gap-2">
          <span className="font-semibold text-ink">{row.child_name || <span className="text-ink-subtle">{t('не указан')}</span>}</span>
          {row.is_stale && <span className="size-2 shrink-0 rounded-full bg-warning-600" title={t('Висит без движения')} />}
        </span>
      ),
      mobileRender: row => row.child_name || row.parent_name,
    },
    { key: 'child_age', header: t('Возраст'), sortable: true, render: row => row.child_age ?? '—', mobileRender: row => (row.child_age == null ? null : row.child_age) },
    { key: 'parent_name', header: t('Родитель'), sortable: true },
    { key: 'phone', header: t('Телефон'), sortable: true, render: row => <a href={`tel:${row.phone}`} onClick={e => e.stopPropagation()} className="whitespace-nowrap hover:text-brand-700">{row.phone}</a> },
    { key: 'direction', header: t('Направление'), sortable: true, render: row => row.direction_name || '—', mobileRender: row => row.direction_name || null },
    { key: 'source', header: t('Источник'), sortable: true, render: row => (row.source_name ? t(row.source_name) : '—'), mobileRender: row => (row.source_name ? t(row.source_name) : null) },
    { key: 'status', header: t('Статус'), sortable: true, mobileAside: true, render: row => <Badge tone={stageBadge(row).tone}>{stageBadge(row).label}</Badge> },
    {
      key: 'assigned_to',
      header: t('Ответственный'),
      sortable: true,
      render: row => (row.assigned_to_name ? <span className="flex items-center gap-2 whitespace-nowrap"><Avatar name={row.assigned_to_name} className="!size-6 !text-[9px]" />{row.assigned_to_name}</span> : '—'),
      mobileRender: row => row.assigned_to_name || null,
    },
    { key: 'created_at', header: t('Создана'), sortable: true, render: row => <span className="whitespace-nowrap text-ink-muted">{formatDateTime(row.created_at)}</span> },
    {
      key: 'days_in_status',
      header: t('Дней в статусе'),
      sortable: true,
      align: 'right',
      render: row => <span className={cn(row.is_stale ? 'font-semibold text-warning-600' : 'text-ink-muted')}>{row.days_in_status}</span>,
    },
  ]

  // Массовая смена — по основным этапам (ролям), названия — центра (TRU-154).
  const statusOptions = LEAD_STATUSES.map(s => ({ value: s.value, label: stages.find(st => st.is_system && st.role === s.value)?.name || s.label }))
  const staffOptions = [{ value: '', label: t('Не назначен') }, ...staff.map(u => ({ value: u.id, label: u.full_name }))]

  return (
    <>
      <div className="mb-3 flex min-h-10 flex-wrap items-center gap-2">
        {selected.size > 0 ? (
          <>
            <span className="text-[13px] font-semibold text-ink">{t('Выбрано: {n}', { n: selected.size })}</span>
            <div className="w-48">
              <Dropdown size="sm" value="" placeholder={t('Сменить статус…')} options={statusOptions} ariaLabel={t('Сменить статус')} disabled={busy}
                onChange={to => (to === 'rejected' ? setRejecting(true) : bulk({ action: 'status', status: to }))} />
            </div>
            <div className="w-48">
              <Dropdown size="sm" value="" placeholder={t('Назначить…')} options={staffOptions} ariaLabel={t('Назначить ответственного')} disabled={busy}
                onChange={userId => bulk({ action: 'assign', assigned_to: userId || null })} />
            </div>
            <Button size="sm" variant="ghost" icon={X} onClick={() => setSelected(new Set())}>{t('Снять выбор')}</Button>
          </>
        ) : (
          <span className="hidden text-[13px] text-ink-muted md:inline">{t('Отметьте заявки, чтобы сменить статус или ответственного сразу у нескольких.')}</span>
        )}
        <Button size="sm" icon={Download} onClick={exportExcel} className="ml-auto">{t('Excel')}</Button>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={data.error}
        onRetry={() => setRefresh(r => r + 1)}
        sort={sort}
        onSortChange={next => update({ ordering: next.dir === 'desc' ? `-${next.key}` : next.key, page: '' })}
        pagination={{ page, pageSize: PAGE_SIZE, total: data.count }}
        onPageChange={next => { update({ page: next > 1 ? String(next) : '' }); window.scrollTo({ top: 0 }) }}
        onRowClick={row => navigate(`/leads/${row.id}`, { state: { leadsReturnTo: returnTo } })}
        empty={hasFilters ? (
          <EmptyState icon={Search} title={t('Ничего не нашли')} description={t('Попробуйте изменить поиск или сбросить фильтры.')} action={<Button size="sm" onClick={onReset}>{t('Сбросить фильтры')}</Button>} />
        ) : (
          <EmptyState icon={Inbox} title={t('Заявок пока нет')} description={t('Заявки из Instagram, WhatsApp и звонков появятся здесь — по колонкам воронки.')} />
        )}
      />

      {rejecting && (
        <RejectModal
          kind={query.kind || 'new'}
          subject={`${selected.size} ${plural(selected.size, ['заявка', 'заявки', 'заявок'])}`}
          onCancel={() => setRejecting(false)}
          onConfirm={async extra => { setRejecting(false); await bulk({ action: 'status', status: 'rejected', ...extra }) }}
        />
      )}
    </>
  )
}
