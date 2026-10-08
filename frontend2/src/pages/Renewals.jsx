import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CalendarClock, Check, Download, Inbox, MessageCircle, Phone, RefreshCw, Search } from 'lucide-react'
import api from '../api/axios'
import RenewModal from '../components/money/RenewModal'
import WhatsAppBulkModal from '../components/messaging/WhatsAppBulkModal'
import { useSession } from '../session/SessionContext'
import {
  Badge, Button, DataTable, EmptyState, FilterBar, FilterCheck, FilterPanel, FilterSelect,
  PageHeader, SearchInput, apiErrorMessage, cn, formatDate, formatDateTime, plural, useFilterDraft, useToast,
} from '../ui'
import { t } from '../i18n'

const PANEL_KEYS = ['branch', 'direction', 'group', 'not_contacted']
const FILTER_KEYS = ['q', ...PANEL_KEYS]
const PAGE_SIZE = 25

function waLink(phone, text) {
  return `https://wa.me/${phone.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`
}

function whenLabel(row) {
  if (row.days_left < 0) return t('закончился')
  if (row.days_left === 0) return t('сегодня')
  return t('через {n} дн.', { n: row.days_left })
}

/** «Продления» (TRU-69): рабочий список администратора на каждый день. */
export default function Renewals() {
  const navigate = useNavigate()
  const toast = useToast()
  const [exporting, setExporting] = useState(false)
  const { can, activeBranch, activeBranchId, branches } = useSession()
  const canLeads = can('can_manage_leads')
  // Преподаватель с открытыми финансами (TRU-153) список видит, но не меняет.
  const canChange = can('can_change_client_money')
  const [params, setParams] = useSearchParams()
  const [loaded, setLoaded] = useState({ key: null, data: { results: [], count: 0 }, error: false })
  const [reloadKey, setReloadKey] = useState(0)
  const [directions, setDirections] = useState([])
  const [groups, setGroups] = useState([])
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [renewing, setRenewing] = useState(null)
  const [busy, setBusy] = useState(null)
  const [selected, setSelected] = useState(() => new Set())
  const [bulkOpen, setBulkOpen] = useState(false)

  const page = Math.max(1, Number(params.get('page')) || 1)
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
    Promise.all([api.get('directions/'), api.get('groups/')])
      .then(([d, g]) => { setDirections(d.data.results || d.data); setGroups(g.data.results || g.data) })
      .catch(() => {})
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
    const request = { ...Object.fromEntries(new URLSearchParams(query)), page_size: PAGE_SIZE }
    api.get('subscriptions/renewals/', { params: request, signal: controller.signal })
      .then(response => setLoaded({ key: requestKey, data: response.data, error: false }))
      .catch(err => {
        if (err.name !== 'CanceledError') setLoaded(prev => ({ ...prev, key: requestKey, error: true }))
      })
    return () => controller.abort()
  }, [query, requestKey])
  const { data, error } = loaded
  const loading = loaded.key !== requestKey
  const reload = () => setReloadKey(k => k + 1)

  const branchGroups = useMemo(
    () => (activeBranchId ? groups.filter(g => !g.branch || String(g.branch) === String(activeBranchId)) : groups),
    [groups, activeBranchId],
  )
  const activeFilters = PANEL_KEYS.filter(key => params.get(key)).length
  const hasAnyFilter = activeFilters > 0 || Boolean(params.get('q'))
  const setQuery = useCallback(q => update({ q }), [update])
  const resetFilters = () => update(Object.fromEntries(FILTER_KEYS.map(key => [key, ''])))
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

  async function markContacted(row) {
    setBusy(`contact:${row.subscription_id}`)
    try {
      await api.post(`subscriptions/renewals/${row.subscription_id}/contacted/`, {})
      toast.success(t('Отмечено: связались с {name}', { name: row.parent_name || row.child_name }))
      reload()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function openRenewalLead(row) {
    if (row.renewal_lead_id) { navigate(`/leads/${row.renewal_lead_id}`); return }
    setBusy(`lead:${row.subscription_id}`)
    try {
      const { data: lead } = await api.post('leads/renewal/', { child: row.child_id })
      navigate(`/leads/${lead.id}`)
    } catch (err) {
      toast.error(apiErrorMessage(err))
      setBusy(null)
    }
  }

  const columns = [
    {
      key: 'child',
      header: t('Ребёнок'),
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
          <div className="truncate text-xs text-ink-muted">{[row.group_name || row.direction_name, !activeBranch && row.branch_name].filter(Boolean).join(' · ')}</div>
        </div>
      ),
      mobileRender: row => <span className="text-ink-muted">{row.subscription_name} · {row.group_name || row.direction_name}</span>,
    },
    {
      key: 'ends',
      header: t('Заканчивается'),
      mobileAside: true,
      render: row => (
        <div className="whitespace-nowrap">
          <div className={cn('font-semibold', row.days_left <= 3 ? 'text-danger-600' : 'text-warning-600')}>{whenLabel(row)}</div>
          <div className="text-xs text-ink-muted">
            {formatDate(row.ends_on)}
            {row.sessions_remaining != null && ` · ${t('занятий: {n}', { n: row.sessions_remaining })}`}
          </div>
        </div>
      ),
    },
    {
      key: 'contact',
      header: t('Связь'),
      render: row => (row.last_contacted_at ? (
        <div className="min-w-0" title={row.last_contact_note || undefined}>
          <Badge tone={row.contacted_recently ? 'success' : 'neutral'}>{t('Связались')}</Badge>
          <div className="mt-0.5 truncate text-xs text-ink-muted">{formatDateTime(row.last_contacted_at)} · {row.last_contacted_by}</div>
        </div>
      ) : <span className="text-xs text-ink-subtle">{t('Ещё не звонили')}</span>),
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('Действия')}</span>,
      render: row => (
        <div className="flex flex-wrap items-center justify-end gap-1.5" onClick={e => e.stopPropagation()}>
          {row.phone && (
            <a href={`tel:${row.phone}`} className="flex size-9 items-center justify-center rounded-md text-ink-muted hover:bg-surface-muted hover:text-ink" title={t('Позвонить')} aria-label={t('Позвонить')}>
              <Phone className="size-4" />
            </a>
          )}
          {row.whatsapp && (
            <a href={waLink(row.whatsapp, row.message_text)} target="_blank" rel="noreferrer" className="flex size-9 items-center justify-center rounded-md text-success-600 hover:bg-success-50" title={t('Написать в WhatsApp')} aria-label={t('Написать в WhatsApp')}>
              <MessageCircle className="size-4" />
            </a>
          )}
          {canChange && (
            <Button size="sm" variant="ghost" icon={Check} loading={busy === `contact:${row.subscription_id}`} onClick={() => markContacted(row)} title={t('Отметить, что связались')}>
              <span className="hidden 2xl:inline">{t('Связались')}</span>
            </Button>
          )}
          {canLeads && (
            <Button size="sm" variant="ghost" icon={Inbox} loading={busy === `lead:${row.subscription_id}`} onClick={() => openRenewalLead(row)} title={row.renewal_lead_id ? t('Открыть заявку на продление') : t('Завести заявку на продление')}>
              <span className="hidden 2xl:inline">{row.renewal_lead_id ? t('Заявка') : t('В заявки')}</span>
            </Button>
          )}
          {canChange && <Button size="sm" variant="primary" icon={RefreshCw} onClick={() => setRenewing(row)}>{t('Продлить')}</Button>}
        </div>
      ),
    },
  ]

  const countLabel = `${data.count} ${plural(data.count, ['абонемент', 'абонемента', 'абонементов'])}`

  // Та же выборка файлом — сверка с бухгалтерией (TRU-152).
  async function exportExcel() {
    setExporting(true)
    try {
      const res = await api.get('subscriptions/renewals/export/', { params: Object.fromEntries(new URLSearchParams(query)), responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const link = Object.assign(document.createElement('a'), { href: url, download: `renewals-${new Date().toISOString().slice(0, 10)}.xlsx` })
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('Продления')}
        description={loading && !data.count ? t('Загрузка…') : `${countLabel} ${t('скоро заканчиваются')}${hasAnyFilter ? ` ${t('по фильтрам')}` : ''}${activeBranch ? ` · ${activeBranch.name}` : ''}`}
        actions={(
          <>
            <Button icon={MessageCircle} disabled={!selected.size} onClick={() => setBulkOpen(true)}>{t('Напомнить в WhatsApp')} {selected.size ? `(${selected.size})` : ''}</Button>
            <Button icon={Download} loading={exporting} onClick={exportExcel} disabled={!data.count}>{t('Скачать Excel')}</Button>
          </>
        )}
      />

      <div className="mb-4 space-y-3">
        <FilterBar
          search={<SearchInput value={params.get('q') || ''} onChange={setQuery} placeholder={t('Поиск по имени ребёнка')} />}
          filtersOpen={filtersOpen}
          onToggleFilters={() => setFiltersOpen(o => !o)}
          activeCount={activeFilters}
        />
        {filtersOpen && (
          <RenewalFilters params={params} update={update} branches={branches} directions={directions} groups={branchGroups} onReset={resetFilters} />
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
        onRetry={reload}
        pagination={{ page, pageSize: PAGE_SIZE, total: data.count }}
        onPageChange={next => { update({ page: next > 1 ? String(next) : '' }, { resetPage: false }); window.scrollTo({ top: 0 }) }}
        onRowClick={row => navigate(`/children/${row.child_id}?tab=subscriptions`)}
        empty={hasAnyFilter ? (
          <EmptyState
            icon={Search}
            title={t('Никого не нашли')}
            description={t('Попробуйте изменить поиск или сбросить фильтры.')}
            action={<Button size="sm" onClick={resetFilters}>{t('Сбросить фильтры')}</Button>}
          />
        ) : (
          <EmptyState icon={CalendarClock} title={t('Продлевать пока некого')} description={t('Здесь появятся абонементы, которые скоро закончатся по сроку или по занятиям.')} />
        )}
      />

      {renewing && (
        <RenewModal row={renewing} onClose={() => setRenewing(null)} onDone={() => { setRenewing(null); reload() }} />
      )}
      <WhatsAppBulkModal open={bulkOpen} onClose={() => setBulkOpen(false)} source="renewals" ids={[...selected]} onSent={() => setSelected(new Set())} />
    </div>
  )
}

function RenewalFilters({ params, update, branches, directions, groups, onReset }) {
  const applied = Object.fromEntries(PANEL_KEYS.map(key => [key, params.get(key) || '']))
  const { draft, set, dirty } = useFilterDraft(applied)
  return (
    <FilterPanel
      dirty={dirty}
      canReset={PANEL_KEYS.some(key => applied[key])}
      onApply={() => update(draft)}
      onReset={onReset}
      checks={<FilterCheck label={t('Не звонили за неделю')} checked={draft.not_contacted === '1'} onChange={v => set('not_contacted', v ? '1' : '')} />}
    >
      {branches.length > 1 && (
        <FilterSelect label={t('Филиал')} value={draft.branch} onChange={v => set('branch', v)} options={[['', t('Как в шапке')], ...branches.map(b => [String(b.id), b.name])]} />
      )}
      <FilterSelect label={t('Направление')} value={draft.direction} onChange={v => set('direction', v)} options={[['', t('Все направления')], ...directions.map(d => [String(d.id), d.name])]} />
      <FilterSelect label={t('Группа')} value={draft.group} onChange={v => set('group', v)} options={[['', t('Все группы')], ...groups.map(g => [String(g.id), g.name])]} />
    </FilterPanel>
  )
}
