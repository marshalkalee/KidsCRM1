import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Clock, Plus, UsersRound } from 'lucide-react'
import api from '../api/axios'
import GroupModal from '../components/GroupModal'
import { useSession } from '../session/SessionContext'
import { Avatar, Badge, Button, Card, Checkbox, EmptyState, ErrorState, PageHeader, Select, Skeleton, cn, plural } from '../ui'
import FillBar from '../components/groups/FillBar'
import { GROUP_STATUSES, scheduleSummary } from '../components/groups/format'

const STATUS_TABS = [['active', 'Набирают'], ['paused', 'Приостановлены'], ['closed', 'Закрытые'], ['', 'Все']]
const listOf = r => r.data.results || r.data

/**
 * Группы (TRU-87): карточки с цветом направления, расписанием и
 * заполняемостью. «Недобор» — по порогу из настроек организации (сервер
 * считает is_underfilled). Фильтры — в адресе; филиал — из шапки.
 */
export default function Groups() {
  const { can, activeBranchId, activeBranch } = useSession()
  const canManage = can('can_manage_groups')
  const [params, setParams] = useSearchParams()
  const [groups, setGroups] = useState(null)
  const [error, setError] = useState(false)
  const [directions, setDirections] = useState([])
  const [teachers, setTeachers] = useState([])
  const [creating, setCreating] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  const status = params.has('status') ? params.get('status') : 'active'
  const direction = params.get('direction') || ''
  const teacher = params.get('teacher') || ''
  const underfilledOnly = params.get('underfilled') === '1'

  const update = useCallback(changes => setParams(current => {
    const next = new URLSearchParams(current)
    Object.entries(changes).forEach(([key, value]) => {
      if (value === null || value === false || (value === '' && key !== 'status')) next.delete(key)
      else next.set(key, value === true ? '1' : value)
    })
    return next
  }, { replace: true }), [setParams])

  useEffect(() => {
    Promise.all([api.get('directions/'), api.get('users/', { params: { role: 'teacher' } })])
      .then(([d, t]) => { setDirections(listOf(d)); setTeachers(listOf(t)) })
      .catch(() => {})
  }, [])

  const requestKey = `${status}|${direction}|${teacher}|${activeBranchId}|${reloadKey}`
  useEffect(() => {
    const controller = new AbortController()
    const query = { status: status || undefined, direction: direction || undefined, teacher: teacher || undefined, branch: activeBranchId || undefined }
    api.get('groups/', { params: query, signal: controller.signal })
      .then(r => { setGroups({ key: requestKey, rows: listOf(r) }); setError(false) })
      .catch(err => { if (err.name !== 'CanceledError') setError(true) })
    return () => controller.abort()
  }, [status, direction, teacher, activeBranchId, requestKey])

  const loading = groups?.key !== requestKey
  const rows = (groups?.rows || []).filter(g => !underfilledOnly || g.is_underfilled)
  const underfilledCount = (groups?.rows || []).filter(g => g.is_underfilled).length

  return (
    <div>
      <PageHeader
        title="Группы"
        description={groups ? `${rows.length} ${plural(rows.length, ['группа', 'группы', 'групп'])}${activeBranch ? ` · ${activeBranch.name}` : ''}${underfilledCount ? ` · с недобором: ${underfilledCount}` : ''}` : 'Загрузка…'}
        actions={canManage && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Создать группу</Button>}
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-line bg-surface p-0.5" role="group" aria-label="Статус">
          {STATUS_TABS.map(([value, label]) => (
            <button
              key={value || 'all'}
              type="button"
              aria-pressed={status === value}
              onClick={() => update({ status: value })}
              className={cn('h-8 whitespace-nowrap rounded px-3 text-[13px] font-medium', status === value ? 'bg-brand-50 text-brand-700 shadow-card' : 'text-ink-muted hover:text-ink')}
            >
              {label}
            </button>
          ))}
        </div>
        <Select aria-label="Направление" className="h-9 w-48" value={direction} onChange={e => update({ direction: e.target.value })}>
          <option value="">Все направления</option>
          {directions.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
        </Select>
        {teachers.length > 0 && (
          <Select aria-label="Преподаватель" className="h-9 w-48" value={teacher} onChange={e => update({ teacher: e.target.value })}>
            <option value="">Все преподаватели</option>
            {teachers.map(t => <option key={t.id} value={t.id}>{t.full_name}</option>)}
          </Select>
        )}
        <Checkbox className="ml-1" label="Только с недобором" checked={underfilledOnly} onChange={e => update({ underfilled: e.target.checked })} />
      </div>

      {error && <Card><ErrorState onRetry={() => setReloadKey(k => k + 1)} /></Card>}
      {!error && !groups && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-52" />)}</div>
      )}
      {!error && groups && rows.length === 0 && (
        <Card>
          <EmptyState
            icon={UsersRound}
            title={underfilledOnly ? 'Групп с недобором нет' : 'Групп нет'}
            description={underfilledOnly ? 'Все группы заполнены выше порога из настроек.' : 'Создайте группу — в неё записываются дети, по ней строится расписание.'}
            action={canManage && !underfilledOnly && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>Создать группу</Button>}
          />
        </Card>
      )}
      {rows.length > 0 && (
        <div className={cn('grid gap-4 md:grid-cols-2 xl:grid-cols-3', loading && 'opacity-60')}>
          {rows.map(group => <GroupCard key={group.id} group={group} />)}
        </div>
      )}

      {creating && (
        <GroupModal onClose={() => setCreating(false)} onSaved={() => { setCreating(false); setReloadKey(k => k + 1) }} />
      )}
    </div>
  )
}

function GroupCard({ group }) {
  const status = GROUP_STATUSES[group.status]
  const full = group.members_count >= group.capacity
  const schedule = scheduleSummary(group.schedule)
  return (
    <Link to={`/groups/${group.id}`} className="group relative flex flex-col overflow-hidden rounded-lg border border-line bg-surface p-5 pl-6 shadow-card transition-shadow hover:shadow-pop">
      <span className="absolute inset-y-0 left-0 w-1.5" style={{ backgroundColor: group.direction_color || '#9aa3ad' }} />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-base font-bold text-ink group-hover:text-brand-700">{group.name}</p>
          <p className="mt-0.5 truncate text-[13px] text-ink-muted">
            {group.direction_name} · {group.branch_name}
            {group.age_min != null && group.age_max != null && ` · ${group.age_min}–${group.age_max} лет`}
          </p>
        </div>
        {group.status !== 'active' ? <Badge tone={status.tone}>{status.label}</Badge>
          : full ? <Badge tone="danger">Мест нет</Badge>
            : group.is_underfilled ? <Badge tone="warning">Недобор</Badge> : null}
      </div>

      <p className="mt-3 flex items-center gap-1.5 text-[13px] text-ink-muted">
        <Clock className="size-3.5 shrink-0" />
        {schedule || <span className="text-ink-subtle">расписание не задано</span>}
      </p>

      <div className="mt-3 flex min-h-7 items-center gap-2">
        {group.teachers_detail.length ? (
          <>
            <div className="flex -space-x-2">
              {group.teachers_detail.slice(0, 3).map(t => <Avatar key={t.id} name={t.full_name} className="size-7 text-[10px] ring-2 ring-surface" />)}
            </div>
            <span className="truncate text-[13px] text-ink-muted">{group.teachers_detail.map(t => t.full_name.split(' ')[0]).join(', ')}</span>
          </>
        ) : <span className="text-[13px] text-ink-subtle">Преподаватель не назначен</span>}
      </div>

      <FillBar group={group} className="mt-auto pt-4" />
    </Link>
  )
}
