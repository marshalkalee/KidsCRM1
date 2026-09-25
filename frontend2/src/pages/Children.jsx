import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, Plus, Search, Upload, Users } from 'lucide-react'
import api from '../api/axios'
import ChildModal from '../components/ChildModal'
import { useSession } from '../session/SessionContext'
import {
  Avatar, Badge, Button, CHILD_STATUSES, DataTable, EmptyState, FilterBar, FilterCheck, FilterPanel, FilterSelect,
  PageHeader, SearchInput, ageLabel, formatDate, money, plural, useFilterDraft,
} from '../ui'

// Всё состояние списка — в адресной строке: ссылку с фильтрами можно
// переслать коллеге, «назад» из карточки возвращает туда же. Последние
// фильтры ещё и запоминаются — чтобы, открыв «Дети» из меню, не выставлять
// их заново.
const FILTER_KEYS = ['q', 'branch', 'status', 'direction', 'group', 'has_debt', 'expiring']
const PANEL_KEYS = FILTER_KEYS.filter(key => key !== 'q')
const MONEY_KEYS = ['has_debt', 'expiring']
const STORAGE_KEY = 'kc:children-list'
const PAGE_SIZE = 25

const STATUS_OPTIONS = [['', 'Все статусы'], ...Object.entries(CHILD_STATUSES).map(([value, s]) => [value, s.label])]

function readStored() {
  try { return localStorage.getItem(STORAGE_KEY) } catch { return null }
}
function writeStored(value) {
  try { localStorage.setItem(STORAGE_KEY, value) } catch { /* приватный режим */ }
}

export default function Children() {
  const navigate = useNavigate()
  const { can, activeBranch, activeBranchId, branches } = useSession()
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
        return <Badge tone={status.tone}>{status.label}</Badge>
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

  const countLabel = `${data.count} ${plural(data.count, ['ребёнок', 'ребёнка', 'детей'])}`

  return (
    <div>
      <PageHeader
        title="Дети"
        description={loading && !data.count ? 'Загрузка…' : `${countLabel}${hasAnyFilter ? ' по фильтрам' : ''}${activeBranch ? ` · ${activeBranch.name}` : ''}`}
        actions={canManage && (
          <>
            <Button icon={Upload} onClick={() => navigate('/children/import')}>Импорт из Excel</Button>
            <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Добавить ребёнка</Button>
          </>
        )}
      />

      <div className="mb-4 space-y-3">
        <FilterBar
          search={<SearchInput value={params.get('q') || ''} onChange={setQuery} placeholder="Поиск по имени ребёнка" />}
          filtersOpen={filtersOpen}
          onToggleFilters={() => setFiltersOpen(o => !o)}
          activeCount={activeFilters}
        />
        {filtersOpen && (
          <ChildFilters params={params} update={update} branches={branches} directions={directions} groups={branchGroups} showMoney={showMoney} onReset={resetFilters} />
        )}
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

      {creating && (
        <ChildModal
          onClose={() => setCreating(false)}
          onSaved={child => { setCreating(false); navigate(`/children/${child.id}`) }}
        />
      )}
    </div>
  )
}

/** Панель фильтров как в первом React: правки применяются кнопкой «Применить». */
function ChildFilters({ params, update, branches, directions, groups, showMoney, onReset }) {
  const applied = Object.fromEntries(PANEL_KEYS.map(key => [key, params.get(key) || '']))
  const { draft, set, dirty } = useFilterDraft(applied)
  const canReset = PANEL_KEYS.some(key => applied[key])
  return (
    <FilterPanel
      dirty={dirty}
      canReset={canReset}
      onApply={() => update(draft)}
      onReset={onReset}
      checks={showMoney && (
        <>
          <FilterCheck label="Есть задолженность" checked={draft.has_debt === '1'} onChange={v => set('has_debt', v ? '1' : '')} />
          <FilterCheck label="Абонемент скоро заканчивается" checked={draft.expiring === '1'} onChange={v => set('expiring', v ? '1' : '')} />
        </>
      )}
    >
      {branches.length > 1 && (
        <FilterSelect label="Филиал" value={draft.branch} onChange={v => set('branch', v)} options={[['', 'Как в шапке'], ...branches.map(b => [String(b.id), b.name])]} />
      )}
      <FilterSelect label="Направление" value={draft.direction} onChange={v => set('direction', v)} options={[['', 'Все направления'], ...directions.map(d => [String(d.id), d.name])]} />
      <FilterSelect label="Группа" value={draft.group} onChange={v => set('group', v)} options={[['', 'Все группы'], ...groups.map(g => [String(g.id), g.name])]} />
      <FilterSelect label="Статус" value={draft.status} onChange={v => set('status', v)} options={STATUS_OPTIONS} />
    </FilterPanel>
  )
}

/** «А, Б, В, Г» → «А, Б +2»: строка таблицы не раздувается, полный список — в подсказке. */
function NameList({ value, limit = 2 }) {
  const names = !value || value === '—' ? [] : value.split(', ')
  if (!names.length) return <span className="text-ink-subtle">—</span>
  const rest = names.length - limit
  return (
    <span className="text-ink-muted" title={rest > 0 ? value : undefined}>
      {names.slice(0, limit).map((name, i) => (
        <span key={name}>{i > 0 && ', '}<span className="whitespace-nowrap">{name}</span></span>
      ))}
      {rest > 0 && <span className="ml-1.5 rounded-full bg-surface-muted px-1.5 py-0.5 text-[11px] font-semibold text-ink-muted">+{rest}</span>}
    </span>
  )
}
