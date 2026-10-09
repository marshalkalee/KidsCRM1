import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Download, MessageCircle, Phone, Search, Wallet } from 'lucide-react'
import api from '../api/axios'
import AcceptPaymentModal from '../components/money/AcceptPaymentModal'
import WhatsAppBulkModal from '../components/messaging/WhatsAppBulkModal'
import { useSession } from '../session/SessionContext'
import {
  Button, Card, DataTable, EmptyState, FilterBar, FilterCheck, FilterPanel, FilterSelect,
  PageHeader, SearchInput, apiErrorMessage, cn, money, plural, useFilterDraft, useToast,
} from '../ui'
import { t } from '../i18n'

// Состояние — в адресе, как у списка детей: ссылку с фильтром можно переслать.
const PANEL_KEYS = ['branch', 'direction', 'overdue']
const FILTER_KEYS = ['q', ...PANEL_KEYS]
const PAGE_SIZE = 25

function waLink(phone, text) {
  return `https://wa.me/${phone.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`
}
/** «Задолженности» (TRU-68): деньги, которые центр заработал, но не получил. */
export default function Debts() {
  const navigate = useNavigate()
  const toast = useToast()
  const { can, activeBranch, activeBranchId, branches } = useSession()
  const canAccept = can('can_accept_payments')
  const [params, setParams] = useSearchParams()
  const [loaded, setLoaded] = useState({ key: null, data: { results: [], count: 0 }, error: false })
  const [reloadKey, setReloadKey] = useState(0)
  const [directions, setDirections] = useState([])
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [paying, setPaying] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [selected, setSelected] = useState(() => new Set())
  const [bulkOpen, setBulkOpen] = useState(false)

  const page = Math.max(1, Number(params.get('page')) || 1)
  const sort = { key: params.get('sort') || 'debt', dir: params.get('dir') || 'desc' }
  const query = params.toString()

  const update = useCallback((changes, { resetPage = true } = {}) => {
    setParams(current => {
      const next = new URLSearchParams(current)
      Object.entries(changes).forEach(([key, value]) => {
        if (value === '' || value == null || value === false) next.delete(key)
        else next.set(key, value === true ? '1' : value)
      })
      if (resetPage) next.delete('page')
      return next
    }, { replace: true })
  }, [setParams])

  useEffect(() => {
    api.get('directions/').then(r => setDirections(r.data.results || r.data)).catch(() => {})
  }, [])

  const firstBranch = useRef(activeBranchId)
  useEffect(() => {
    if (firstBranch.current === activeBranchId) return
    firstBranch.current = activeBranchId
    update({})
  }, [activeBranchId, update])

  const requestKey = `${query}|${activeBranchId}|${reloadKey}`
  useEffect(() => {
    const controller = new AbortController()
    const request = { sort: 'debt', dir: 'desc', ...Object.fromEntries(new URLSearchParams(query)), page_size: PAGE_SIZE }
    api.get('subscriptions/debtors/', { params: request, signal: controller.signal })
      .then(response => setLoaded({ key: requestKey, data: response.data, error: false }))
      .catch(err => {
        if (err.name !== 'CanceledError') setLoaded(prev => ({ ...prev, key: requestKey, error: true }))
      })
    return () => controller.abort()
  }, [query, requestKey])
  const { data, error } = loaded
  const loading = loaded.key !== requestKey

  const activeFilters = PANEL_KEYS.filter(key => params.get(key)).length
  const hasAnyFilter = activeFilters > 0 || Boolean(params.get('q'))
  const setQuery = useCallback(q => update({ q }), [update])
  const resetFilters = () => update(Object.fromEntries(FILTER_KEYS.map(key => [key, ''])))
  const overdueDays = data.overdue_days ?? 5
  const visibleIds = data.results.map(row => row.subscription_id)
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => selected.has(id))
  function toggleSelected(id) {
    setSelected(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  function toggleVisible() {
    setSelected(current => {
      const next = new Set(current)
      visibleIds.forEach(id => allVisibleSelected ? next.delete(id) : next.add(id))
      return next
    })
  }

  async function exportExcel() {
    setExporting(true)
    try {
      const request = { ...Object.fromEntries(new URLSearchParams(query)) }
      const res = await api.get('subscriptions/debtors/export/', { params: request, responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const link = Object.assign(document.createElement('a'), { href: url, download: `debts-${new Date().toISOString().slice(0, 10)}.xlsx` })
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  const columns = [
    {
      key: 'child',
      header: t('Ребёнок'),
      sortable: true,
      primary: true,
      render: row => (
        <div className="flex min-w-0 items-center gap-3" onClick={event => event.stopPropagation()}>
          <input type="checkbox" checked={selected.has(row.subscription_id)} onChange={() => toggleSelected(row.subscription_id)} aria-label={t('Выбрать {name}', { name: row.child_name })} className="size-4 accent-[var(--color-brand-500)]" />
          <div className="min-w-0">
            <div className="truncate font-semibold text-ink">{row.child_name}</div>
            <div className="truncate text-xs text-ink-muted">{row.parent_name || t('Плательщик не указан')}</div>
          </div>
        </div>
      ),
    },
    {
      key: 'subscription',
      header: t('Абонемент'),
      render: row => (
        <div className="min-w-0">
          <div className="truncate text-ink">{row.subscription_name}</div>
          <div className="truncate text-xs text-ink-muted">{[row.direction_name, !activeBranch && row.branch_name].filter(Boolean).join(' · ')}</div>
        </div>
      ),
      mobileRender: row => <span className="text-ink-muted">{row.subscription_name} · {row.direction_name}</span>,
    },
    {
      key: 'debt',
      header: t('Долг'),
      sortable: true,
      align: 'right',
      mobileAside: true,
      render: row => (
        <div className="whitespace-nowrap text-right">
          <div className="font-bold text-danger-600">{money(row.debt)}</div>
          <div className="text-xs text-ink-subtle">{t('из {sum}', { sum: money(row.price) })}</div>
        </div>
      ),
    },
    {
      key: 'age',
      header: t('Давность'),
      sortable: true,
      render: row => (
        <span className={cn('inline-flex items-center gap-1 whitespace-nowrap', row.overdue ? 'font-semibold text-warning-600' : 'text-ink-muted')}>
          {row.overdue && <AlertTriangle className="size-3.5" />}
          {t('{n} дн.', { n: row.age_days })}
        </span>
      ),
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('Действия')}</span>,
      render: row => <RowActions row={row} canAccept={canAccept} onPay={() => setPaying(row)} />,
    },
  ]

  const countLabel = `${data.count} ${plural(data.count, ['абонемент', 'абонемента', 'абонементов'])}`

  return (
    <div>
      <PageHeader
        title={t('Задолженности')}
        description={loading && !data.count ? t('Загрузка…') : `${countLabel} ${t('с долгом')}${hasAnyFilter ? ` ${t('по фильтрам')}` : ''}${activeBranch ? ` · ${activeBranch.name}` : ''}`}
        actions={(
          <>
            <Button icon={MessageCircle} disabled={!selected.size} onClick={() => setBulkOpen(true)}>{t('Напомнить в WhatsApp')} {selected.size ? `(${selected.size})` : ''}</Button>
            <Button icon={Download} loading={exporting} onClick={exportExcel} disabled={!data.count}>{t('Скачать Excel')}</Button>
          </>
        )}
      />

      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <Card className="flex items-center gap-4">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-danger-50 text-danger-600"><Wallet className="size-5" /></span>
          <div>
            <p className="text-[13px] text-ink-muted">{hasAnyFilter ? t('Долг по выборке') : t('Всего долгов')}</p>
            <p className="text-2xl font-bold text-ink">{money(data.total_debt ?? 0)}</p>
          </div>
        </Card>
        <button
          type="button"
          onClick={() => update({ overdue: params.get('overdue') ? '' : '1' })}
          className={cn(
            'flex items-center gap-4 rounded-lg border bg-surface p-5 text-left transition',
            params.get('overdue') ? 'border-warning-600 ring-3 ring-warning-50' : 'border-line hover:border-warning-600',
          )}
        >
          <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-warning-50 text-warning-600"><AlertTriangle className="size-5" /></span>
          <div>
            <p className="text-[13px] text-ink-muted">{t('Просрочено — дольше {n} дн.', { n: overdueDays })}</p>
            <p className="text-2xl font-bold text-ink">
              {money(data.overdue_debt ?? 0)}
              <span className="ml-2 text-sm font-medium text-ink-muted">{t('{n} шт.', { n: data.overdue_count ?? 0 })}</span>
            </p>
          </div>
        </button>
      </div>

      <div className="mb-4 space-y-3">
        <FilterBar
          search={<SearchInput value={params.get('q') || ''} onChange={setQuery} placeholder={t('Поиск по имени ребёнка')} />}
          filtersOpen={filtersOpen}
          onToggleFilters={() => setFiltersOpen(o => !o)}
          activeCount={activeFilters}
        />
        {filtersOpen && (
          <DebtFilters params={params} update={update} branches={branches} directions={directions} overdueDays={overdueDays} onReset={resetFilters} />
        )}
      </div>

      {data.results.length > 0 && (
        <label className="mb-3 inline-flex cursor-pointer items-center gap-2 text-sm font-semibold text-ink-muted">
          <input type="checkbox" checked={allVisibleSelected} onChange={toggleVisible} className="size-4 accent-[var(--color-brand-500)]" />
          {t('Выбрать все на странице')}
        </label>
      )}

      <DataTable
        columns={columns}
        rows={data.results}
        rowKey={row => row.subscription_id}
        loading={loading}
        error={error}
        onRetry={() => setReloadKey(k => k + 1)}
        sort={sort}
        onSortChange={next => update({ sort: next.key, dir: next.dir })}
        pagination={{ page, pageSize: PAGE_SIZE, total: data.count }}
        onPageChange={next => { update({ page: next > 1 ? String(next) : '' }, { resetPage: false }); window.scrollTo({ top: 0 }) }}
        onRowClick={row => navigate(`/children/${row.child_id}?tab=payments`)}
        empty={hasAnyFilter ? (
          <EmptyState
            icon={Search}
            title={t('Никого не нашли')}
            description={t('Попробуйте изменить поиск или сбросить фильтры.')}
            action={<Button size="sm" onClick={resetFilters}>{t('Сбросить фильтры')}</Button>}
          />
        ) : (
          <EmptyState icon={Wallet} title={t('Долгов нет')} description={t('Все абонементы оплачены полностью.')} />
        )}
      />

      {paying && (
        <AcceptPaymentModal
          child={{ id: paying.child_id, full_name: paying.child_name }}
          subscriptionId={paying.subscription_id}
          onClose={() => setPaying(null)}
          onPaid={() => setReloadKey(k => k + 1)}
        />
      )}
      <WhatsAppBulkModal open={bulkOpen} onClose={() => setBulkOpen(false)} source="debts" ids={[...selected]} onSent={() => setSelected(new Set())} />
    </div>
  )
}
/** Звонок, WhatsApp с готовым напоминанием, приём оплаты — не открывая карточку. */
function RowActions({ row, canAccept, onPay }) {
  const stop = e => e.stopPropagation()
  return (
    <div className="flex items-center justify-end gap-1.5" onClick={stop}>
      {row.phone && (
        <a href={`tel:${row.phone}`} className="flex size-9 items-center justify-center rounded-md text-ink-muted hover:bg-surface-muted hover:text-ink" title={t('Позвонить')} aria-label={t('Позвонить')}>
          <Phone className="size-4" />
        </a>
      )}
      {row.whatsapp && (
        <a href={waLink(row.whatsapp, row.reminder_text)} target="_blank" rel="noreferrer" className="flex size-9 items-center justify-center rounded-md text-success-600 hover:bg-success-50" title={t('Напомнить в WhatsApp')} aria-label={t('Напомнить в WhatsApp')}>
          <MessageCircle className="size-4" />
        </a>
      )}
      {canAccept && <Button size="sm" variant="secondary" onClick={onPay}>{t('Принять')}</Button>}
    </div>
  )
}
function DebtFilters({ params, update, branches, directions, overdueDays, onReset }) {
  const applied = Object.fromEntries(PANEL_KEYS.map(key => [key, params.get(key) || '']))
  const { draft, set, dirty } = useFilterDraft(applied)
  return (
    <FilterPanel
      dirty={dirty}
      canReset={PANEL_KEYS.some(key => applied[key])}
      onApply={() => update(draft)}
      onReset={onReset}
      checks={<FilterCheck label={t('Только просроченные (дольше {n} дн.)', { n: overdueDays })} checked={draft.overdue === '1'} onChange={v => set('overdue', v ? '1' : '')} />}
    >
      {branches.length > 1 && (
        <FilterSelect label={t('Филиал')} value={draft.branch} onChange={v => set('branch', v)} options={[['', t('Как в шапке')], ...branches.map(b => [String(b.id), b.name])]} />
      )}
      <FilterSelect label={t('Направление')} value={draft.direction} onChange={v => set('direction', v)} options={[['', t('Все направления')], ...directions.map(d => [String(d.id), d.name])]} />
    </FilterPanel>
  )
}
