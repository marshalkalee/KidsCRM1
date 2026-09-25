import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, Plus, Search, SlidersHorizontal, Upload, Users, X } from 'lucide-react'
import api from '../api/axios'
import ChildModal from '../components/ChildModal'
import { useSession } from '../session/SessionContext'
import {
  Avatar, Badge, Button, CHILD_STATUSES, DataTable, EmptyState, Modal, PageHeader, SearchInput, Select,
  ageLabel, cn, formatDate, money, plural,
} from '../ui'

// Всё состояние списка — в адресной строке: ссылку с фильтрами можно
// переслать коллеге, «назад» из карточки возвращает туда же. Последние
// фильтры ещё и запоминаются — чтобы, открыв «Дети» из меню, не выставлять
// их заново.
const FILTER_KEYS = ['q', 'status', 'direction', 'group', 'has_debt', 'expiring']
const MONEY_KEYS = ['has_debt', 'expiring']
const STORAGE_KEY = 'kc:children-list'
const PAGE_SIZE = 25

const STATUS_TABS = [['', 'Все'], ...Object.entries(CHILD_STATUSES).map(([value, s]) => [value, s.label])]

function readStored() {
  try { return localStorage.getItem(STORAGE_KEY) } catch { return null }
}
function writeStored(value) {
  try { localStorage.setItem(STORAGE_KEY, value) } catch { /* приватный режим */ }
}

export default function Children() {
  const navigate = useNavigate()
  const { can, activeBranch, activeBranchId } = useSession()
  const canManage = can('can_manage_children')
  const showMoney = can('can_view_client_money')
  const [params, setParams] = useSearchParams()

  const [loaded, setLoaded] = useState({ key: null, data: { results: [], count: 0 }, error: false })
  const [reloadKey, setReloadKey] = useState(0)
  const [directions, setDirections] = useState([])
  const [groups, setGroups] = useState([])
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [creating, setCreating] = useState(false)

  const page = Math.max(1, Number(params.get('page')) || 1)
  const sort = { key: params.get('sort') || 'full_name', dir: params.get('dir') || 'asc' }
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

  // Открыли «Дети» из меню (без параметров) — возвращаем последние фильтры.
  const restored = useRef(false)
  useEffect(() => {
    if (restored.current) return
    restored.current = true
    const stored = readStored()
    if (!query && stored) setParams(new URLSearchParams(stored), { replace: true })
  }, [query, setParams])
  useEffect(() => { if (restored.current) writeStored(query) }, [query])

  useEffect(() => {
    Promise.all([api.get('directions/'), api.get('groups/')])
      .then(([d, g]) => {
        setDirections(d.data.results || d.data)
        setGroups(g.data.results || g.data)
      })
      .catch(() => {})
  }, [])

  // Смена филиала в шапке — список с первой страницы.
  const firstBranch = useRef(activeBranchId)
  useEffect(() => {
    if (firstBranch.current === activeBranchId) return
    firstBranch.current = activeBranchId
    update({})
  }, [activeBranchId, update])

  // Пока ответ не для текущих параметров — показываем прежние строки
  // полупрозрачными (loading), а не пустую таблицу.
  const requestKey = `${query}|${activeBranchId}|${reloadKey}`
  useEffect(() => {
    const controller = new AbortController()
    const request = { ...Object.fromEntries(new URLSearchParams(query)), page_size: PAGE_SIZE }
    api.get('clients/children/table/', { params: request, signal: controller.signal })
      .then(response => setLoaded({ key: requestKey, data: response.data, error: false }))
      .catch(err => {
        if (err.name !== 'CanceledError') setLoaded(prev => ({ ...prev, key: requestKey, error: true }))
      })
    return () => controller.abort()
  }, [query, requestKey])
  const { data, error } = loaded
  const loading = loaded.key !== requestKey

  const branchGroups = useMemo(
    () => (activeBranchId ? groups.filter(g => !g.branch || String(g.branch) === String(activeBranchId)) : groups),
    [groups, activeBranchId],
  )
  const activeFilters = FILTER_KEYS.filter(key => key !== 'q' && params.get(key) && (showMoney || !MONEY_KEYS.includes(key))).length
  const hasAnyFilter = activeFilters > 0 || Boolean(params.get('q'))
  const setQuery = useCallback(q => update({ q }), [update])
  const resetFilters = () => update(Object.fromEntries(FILTER_KEYS.map(key => [key, ''])))

  const columns = [
    {
      key: 'full_name',
      header: 'Ребёнок',
      sortable: true,
      primary: true,
      render: row => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={row.full_name} src={row.photo_url} />
          <div className="min-w-0">
            <div className="truncate font-semibold text-ink">{row.full_name}</div>
            <div className="text-xs text-ink-subtle md:hidden">{ageLabel(row.age)}</div>
          </div>
        </div>
      ),
    },
    {
      key: 'age',
      header: 'Возраст',
      sortable: true,
      hideOnMobile: true,
      render: row => (
        <span title={formatDate(row.birth_date)} className="whitespace-nowrap text-ink-muted">{ageLabel(row.age)}</span>
      ),
    },
    { key: 'direction_names', header: 'Направление', render: row => <NameList value={row.direction_names} /> },
    { key: 'group_names', header: 'Группа', render: row => <NameList value={row.group_names} /> },
    ...(activeBranch ? [] : [{ key: 'branch_names', header: 'Филиал', hideOnMobile: true, render: row => <NameList value={row.branch_names} /> }]),
    {
      key: 'status',
      header: 'Статус',
      sortable: true,
      mobileAside: true,
      render: row => {
        const status = CHILD_STATUSES[row.status] || { label: row.status, tone: 'neutral' }
        return <Badge tone={status.tone} dot>{status.label}</Badge>
      },
    },
    ...(data.show_money ? [
      {
        key: 'subscription_name',
        header: 'Абонемент',
        className: 'text-ink-muted',
        render: row => row.subscription_name || '—',
        mobileRender: row => row.subscription_name || null,
      },
      {
        key: 'debt',
        header: 'Долг',
        align: 'right',
        render: row => (Number(row.debt) > 0 ? (
          <span className="inline-flex items-center gap-1 whitespace-nowrap font-semibold text-danger-600">
            <AlertCircle className="size-3.5" />
            {money(row.debt)}
          </span>
        ) : <span className="text-ink-subtle">—</span>),
        mobileRender: row => (Number(row.debt) > 0 ? <span className="font-semibold text-danger-600">{money(row.debt)}</span> : null),
      },
    ] : []),
  ]

  const filterProps = { params, update, directions, groups: branchGroups, showMoney }
  const countLabel = `${data.count} ${plural(data.count, ['ребёнок', 'ребёнка', 'детей'])}`

  return (
    <div>
      <PageHeader
        title="Дети"
        description={loading && !data.count ? 'Загрузка…' : `${countLabel}${hasAnyFilter ? ' по фильтрам' : ''}${activeBranch ? ` · ${activeBranch.name}` : ''}`}
        actions={canManage && (
          <>
            <Button icon={Upload} onClick={() => navigate('/children/import')}>Импорт</Button>
            <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Добавить ребёнка</Button>
          </>
        )}
      />

      <div className="mb-4 space-y-3">
        <div className="flex gap-2">
          <SearchInput className="flex-1" value={params.get('q') || ''} onChange={setQuery} placeholder="Поиск по имени ребёнка" />
          <Button className="lg:hidden" icon={SlidersHorizontal} onClick={() => setFiltersOpen(true)}>
            <span className="hidden sm:inline">Фильтры</span>
            {activeFilters > 0 && (
              <span className="flex size-5 items-center justify-center rounded-full bg-brand-600 text-[11px] text-white">{activeFilters}</span>
            )}
          </Button>
        </div>
        <div className="hidden flex-wrap items-center gap-2 lg:flex">
          <FilterControls {...filterProps} />
          {hasAnyFilter && (
            <Button variant="ghost" size="sm" icon={X} onClick={resetFilters}>Сбросить</Button>
          )}
        </div>
      </div>

      <DataTable
        columns={columns}
        rows={data.results}
        loading={loading}
        error={error}
        onRetry={() => setReloadKey(k => k + 1)}
        sort={sort}
        onSortChange={next => update({ sort: next.key, dir: next.dir })}
        pagination={{ page, pageSize: PAGE_SIZE, total: data.count }}
        onPageChange={next => { update({ page: next > 1 ? String(next) : '' }, { resetPage: false }); window.scrollTo({ top: 0 }) }}
        onRowClick={row => navigate(`/children/${row.id}`)}
        empty={hasAnyFilter ? (
          <EmptyState
            icon={Search}
            title="Никого не нашли"
            description="Попробуйте изменить поиск или сбросить фильтры."
            action={<Button size="sm" onClick={resetFilters}>Сбросить фильтры</Button>}
          />
        ) : (
          <EmptyState
            icon={Users}
            title="Детей пока нет"
            description={canManage ? 'Добавьте первого ребёнка вручную или загрузите список из Excel.' : 'Когда администратор добавит детей, они появятся здесь.'}
            action={canManage && (
              <div className="flex flex-wrap justify-center gap-2">
                <Button size="sm" icon={Upload} onClick={() => navigate('/children/import')}>Импорт из Excel</Button>
                <Button size="sm" variant="primary" icon={Plus} onClick={() => setCreating(true)}>Добавить ребёнка</Button>
              </div>
            )}
          />
        )}
      />

      <Modal
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        title="Фильтры"
        footer={
          <>
            {hasAnyFilter && <Button variant="ghost" onClick={resetFilters}>Сбросить</Button>}
            <Button variant="primary" onClick={() => setFiltersOpen(false)}>Показать: {countLabel}</Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FilterControls {...filterProps} stacked />
        </div>
      </Modal>

      {creating && (
        <ChildModal
          onClose={() => setCreating(false)}
          onSaved={child => { setCreating(false); navigate(`/children/${child.id}`) }}
        />
      )}
    </div>
  )
}

function FilterControls({ params, update, directions, groups, showMoney, stacked = false }) {
  const status = params.get('status') || ''
  return (
    <>
      <div className={cn('flex rounded-md border border-line bg-surface p-0.5', stacked && 'w-full')} role="group" aria-label="Статус">
        {STATUS_TABS.map(([value, label]) => (
          <button
            key={value || 'all'}
            type="button"
            aria-pressed={status === value}
            onClick={() => update({ status: value })}
            className={cn(
              'h-8 flex-1 whitespace-nowrap rounded px-3 text-[13px] font-medium transition-colors',
              status === value ? 'bg-brand-50 text-brand-700 shadow-card' : 'text-ink-muted hover:text-ink',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <Select
        aria-label="Направление"
        className={cn('h-9', !stacked && 'w-44')}
        value={params.get('direction') || ''}
        onChange={e => update({ direction: e.target.value })}
      >
        <option value="">Все направления</option>
        {directions.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
      </Select>
      <Select
        aria-label="Группа"
        className={cn('h-9', !stacked && 'w-44')}
        value={params.get('group') || ''}
        onChange={e => update({ group: e.target.value })}
      >
        <option value="">Все группы</option>
        {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
      </Select>
      {showMoney && (
        <div className={cn('flex gap-2', stacked && 'flex-wrap')}>
          <ToggleChip active={params.get('has_debt') === '1'} onClick={() => update({ has_debt: params.get('has_debt') !== '1' })}>
            С долгом
          </ToggleChip>
          <ToggleChip active={params.get('expiring') === '1'} onClick={() => update({ expiring: params.get('expiring') !== '1' })}>
            Абонемент заканчивается
          </ToggleChip>
        </div>
      )}
    </>
  )
}

/** «А, Б, В, Г» → «А, Б +2»: строка таблицы не раздувается, полный список — в подсказке. */
function NameList({ value, limit = 2 }) {
  const names = !value || value === '—' ? [] : value.split(', ')
  if (!names.length) return <span className="text-ink-subtle">—</span>
  const rest = names.length - limit
  return (
    <span className="text-ink-muted" title={rest > 0 ? value : undefined}>
      {names.slice(0, limit).join(', ')}
      {rest > 0 && <span className="ml-1.5 rounded-full bg-surface-muted px-1.5 py-0.5 text-[11px] font-semibold text-ink-muted">+{rest}</span>}
    </span>
  )
}

function ToggleChip({ active, onClick, children }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'h-9 whitespace-nowrap rounded-full border px-3.5 text-[13px] font-medium transition-colors',
        active ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line bg-surface text-ink-muted hover:border-line-strong hover:text-ink',
      )}
    >
      {children}
    </button>
  )
}
