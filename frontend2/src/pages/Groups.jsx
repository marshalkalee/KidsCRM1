import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Search, UsersRound } from 'lucide-react'
import api from '../api/axios'
import GroupModal from '../components/GroupModal'
import { GROUP_STATUSES, scheduleSummary } from '../components/groups/format'
import { useSession } from '../session/SessionContext'
import {
  Avatar, Badge, Button, DataTable, EmptyState, FilterBar, FilterCheck, FilterPanel, FilterSelect, PageHeader,
  SearchInput, cn, plural, useFilterDraft,
} from '../ui'

const PANEL_KEYS = ['branch', 'direction', 'teacher', 'status', 'underfilled']
const STATUS_OPTIONS = [['', 'Все статусы'], ...Object.entries(GROUP_STATUSES).map(([v, s]) => [v, s.label])]
const listOf = r => r.data.results || r.data

/**
 * Группы (TRU-87, вид первого React — TRU-91): таблица с панелью фильтров.
 * «Недобор» — по порогу из настроек организации (сервер считает
 * is_underfilled). Фильтры в адресе; без своего филиала — филиал из шапки.
 */
export default function Groups() {
  const navigate = useNavigate()
  const { can, activeBranchId, activeBranch, branches } = useSession()
  const canManage = can('can_manage_groups')
  const [params, setParams] = useSearchParams()
  const [loaded, setLoaded] = useState({ key: null, rows: [], error: false })
  const [directions, setDirections] = useState([])
  const [teachers, setTeachers] = useState([])
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  const applied = Object.fromEntries(PANEL_KEYS.map(key => [key, params.get(key) || '']))
  const q = params.get('q') || ''
  const update = useCallback(changes => setParams(current => {
    const next = new URLSearchParams(current)
    Object.entries(changes).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)))
    return next
  }, { replace: true }), [setParams])
  const setQuery = useCallback(value => update({ q: value }), [update])

  useEffect(() => {
    Promise.all([api.get('directions/'), api.get('users/', { params: { role: 'teacher' } })])
      .then(([d, t]) => { setDirections(listOf(d)); setTeachers(listOf(t)) })
      .catch(() => {})
  }, [])

  const branch = applied.branch || activeBranchId || ''
  const requestKey = `${applied.direction}|${applied.teacher}|${applied.status}|${branch}|${q}|${reloadKey}`
  useEffect(() => {
    const controller = new AbortController()
    const query = {
      status: applied.status || undefined,
      direction: applied.direction || undefined,
      teacher: applied.teacher || undefined,
      branch: branch || undefined,
      search: q || undefined,
    }
    api.get('groups/', { params: query, signal: controller.signal })
      .then(r => setLoaded({ key: requestKey, rows: listOf(r), error: false }))
      .catch(err => { if (err.name !== 'CanceledError') setLoaded(prev => ({ ...prev, key: requestKey, error: true })) })
    return () => controller.abort()
  }, [applied.status, applied.direction, applied.teacher, branch, q, requestKey])

  const loading = loaded.key !== requestKey
  const rows = loaded.rows.filter(g => applied.underfilled !== '1' || g.is_underfilled)
  const underfilledCount = loaded.rows.filter(g => g.is_underfilled).length
  const activeCount = PANEL_KEYS.filter(key => applied[key]).length
  const reset = () => update(Object.fromEntries(PANEL_KEYS.map(key => [key, ''])))

  const columns = [
    {
      key: 'name',
      header: 'Название',
      primary: true,
      render: g => (
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: g.direction_color || '#9a93a8' }} />
          <span className="min-w-0">
            <span className="block truncate font-semibold text-ink">{g.name}</span>
            {g.age_min != null && g.age_max != null && <span className="block text-xs text-ink-subtle">{g.age_min}–{g.age_max} лет</span>}
          </span>
        </span>
      ),
    },
    ...(activeBranch ? [] : [{ key: 'branch_name', header: 'Филиал', className: 'text-ink-muted whitespace-nowrap' }]),
    {
      key: 'direction',
      header: 'Направление',
      hideOnMobile: true,
      render: g => (
        <span
          className="inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold"
          style={{ backgroundColor: `color-mix(in srgb, ${g.direction_color || '#9a93a8'} 16%, #fff)`, color: `color-mix(in srgb, ${g.direction_color || '#9a93a8'} 75%, #1f1b2e)` }}
        >
          {g.direction_name}
        </span>
      ),
    },
    {
      key: 'teachers',
      header: 'Преподаватели',
      render: g => (g.teachers_detail.length ? (
        <span className="flex items-center gap-2">
          <span className="flex -space-x-2">
            {g.teachers_detail.slice(0, 3).map(t => <Avatar key={t.id} name={t.full_name} className="size-7 text-[10px] ring-2 ring-surface" />)}
          </span>
          <span className="truncate text-ink-muted">{g.teachers_detail.map(t => t.full_name.split(' ')[0]).join(', ')}</span>
        </span>
      ) : <span className="text-ink-subtle">не назначен</span>),
    },
    { key: 'schedule', header: 'Расписание', hideOnMobile: true, className: 'text-ink-muted whitespace-nowrap', render: g => scheduleSummary(g.schedule) || <span className="text-ink-subtle">—</span> },
    { key: 'fill', header: 'Записано', render: g => <Fill group={g} /> },
    {
      key: 'status',
      header: 'Статус',
      mobileAside: true,
      render: g => {
        const full = g.members_count >= g.capacity
        if (g.status !== 'active') return <Badge tone={GROUP_STATUSES[g.status].tone}>{GROUP_STATUSES[g.status].label}</Badge>
        if (full) return <Badge tone="danger">Мест нет</Badge>
        if (g.is_underfilled) return <Badge tone="warning">Недобор</Badge>
        return <Badge tone="success">Набирает</Badge>
      },
    },
  ]

  return (
    <div>
      <PageHeader
        title="Группы"
        description={`${rows.length} ${plural(rows.length, ['группа', 'группы', 'групп'])}${activeBranch ? ` · ${activeBranch.name}` : ''}${underfilledCount ? ` · с недобором: ${underfilledCount}` : ''}`}
        actions={canManage && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Новая группа</Button>}
      />

      <div className="mb-4 space-y-3">
        <FilterBar
          search={<SearchInput value={q} onChange={setQuery} placeholder="Поиск по названию, направлению, филиалу" />}
          filtersOpen={filtersOpen}
          onToggleFilters={() => setFiltersOpen(o => !o)}
          activeCount={activeCount}
        />
        {filtersOpen && (
          <GroupFilters applied={applied} onApply={update} onReset={reset} branches={branches} directions={directions} teachers={teachers} />
        )}
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={loaded.error}
        onRetry={() => setReloadKey(k => k + 1)}
        onRowClick={g => navigate(`/groups/${g.id}`)}
        empty={activeCount || q ? (
          <EmptyState icon={Search} title="Групп не нашли" description="Измените поиск или сбросьте фильтры." action={<Button size="sm" onClick={reset}>Сбросить фильтры</Button>} />
        ) : (
          <EmptyState
            icon={UsersRound}
            title="Групп пока нет"
            description="Создайте группу — в неё записываются дети, по ней строится расписание."
            action={canManage && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Новая группа</Button>}
          />
        )}
      />

      {creating && (
        <GroupModal onClose={() => setCreating(false)} onSaved={() => { setCreating(false); setReloadKey(k => k + 1) }} />
      )}
    </div>
  )
}

function GroupFilters({ applied, onApply, onReset, branches, directions, teachers }) {
  const { draft, set, dirty } = useFilterDraft(applied)
  return (
    <FilterPanel
      dirty={dirty}
      canReset={PANEL_KEYS.some(key => applied[key])}
      onApply={() => onApply(draft)}
      onReset={onReset}
      checks={<FilterCheck label="Только с недобором" checked={draft.underfilled === '1'} onChange={v => set('underfilled', v ? '1' : '')} />}
    >
      {branches.length > 1 && (
        <FilterSelect label="Филиал" value={draft.branch} onChange={v => set('branch', v)} options={[['', 'Как в шапке'], ...branches.map(b => [String(b.id), b.name])]} />
      )}
      <FilterSelect label="Направление" value={draft.direction} onChange={v => set('direction', v)} options={[['', 'Все направления'], ...directions.map(d => [String(d.id), d.name])]} />
      <FilterSelect label="Преподаватель" value={draft.teacher} onChange={v => set('teacher', v)} options={[['', 'Все преподаватели'], ...teachers.map(t => [String(t.id), t.full_name])]} />
      <FilterSelect label="Статус" value={draft.status} onChange={v => set('status', v)} options={STATUS_OPTIONS} />
    </FilterPanel>
  )
}

/** «8 / 12» с мини-полосой: красная — мест нет, оранжевая — недобор. */
function Fill({ group }) {
  const full = group.members_count >= group.capacity
  const color = full ? 'bg-danger-600' : group.is_underfilled ? 'bg-warning-600' : 'bg-success-600'
  return (
    <span className="flex items-center gap-2.5">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <span className={cn('block h-full rounded-full', color)} style={{ width: `${Math.min(100, Math.max(group.fill_percent ?? 0, 4))}%` }} />
      </span>
      <span className="whitespace-nowrap font-semibold text-ink">{group.members_count}<span className="font-normal text-ink-subtle"> / {group.capacity}</span></span>
    </span>
  )
}
