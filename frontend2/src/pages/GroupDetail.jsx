import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArchiveRestore, CalendarClock, DoorOpen, Lock, Pencil, SearchX, UserMinus, UserPlus, UsersRound } from 'lucide-react'
import api from '../api/axios'
import GroupModal from '../components/GroupModal'
import FillBar from '../components/groups/FillBar'
import { GROUP_STATUSES, WEEKDAYS_SHORT } from '../components/groups/format'
import { useSession } from '../session/SessionContext'
import {
  Avatar, Badge, Button, CHILD_STATUSES, Card, CardHeader, EmptyState, ErrorState, Modal, PageHeader, SearchInput,
  Skeleton, Tabs, ageLabel, apiErrorMessage, cn, formatDate, plural, useConfirm, useToast,
} from '../ui'
import { t } from '../i18n'

const WEEKDAYS_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

/**
 * Карточка группы (TRU-87): заполняемость, расписание, преподаватели,
 * состав с датами и история (кто и когда уходил). Добавить/убрать ребёнка,
 * редактировать, закрыть — владелец и управляющий.
 */
export default function GroupDetail() {
  const { id } = useParams()
  const { can } = useSession()
  const toast = useToast()
  const confirm = useConfirm()
  const canManage = can('can_manage_groups')
  const [params, setParams] = useSearchParams()
  const [group, setGroup] = useState(null)
  const [members, setMembers] = useState([])
  const [history, setHistory] = useState([])
  const [status, setStatus] = useState('loading')
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const tab = params.get('tab') === 'history' ? 'history' : 'members'

  const load = useCallback(() => Promise.all([
    api.get(`groups/${id}/`), api.get(`groups/${id}/members/`), api.get(`groups/${id}/history/`),
  ])
    .then(([g, m, h]) => { setGroup(g.data); setMembers(m.data); setHistory(h.data); setStatus('ready') })
    .catch(err => setStatus(err.response?.status === 404 ? 'missing' : 'error')), [id])

  useEffect(() => { load() }, [load])

  const back = { to: '/groups', label: t('Группы') }
  if (status === 'loading') return <><PageHeader title={<Skeleton className="h-8 w-56" />} back={back} /><Skeleton className="h-64" /></>
  if (status === 'missing') {
    return <Card><EmptyState icon={SearchX} title={t('Группа не найдена')} action={<Button to="/groups">{t('К списку групп')}</Button>} /></Card>
  }
  if (status === 'error') return <Card><ErrorState onRetry={load} /></Card>

  const groupStatus = GROUP_STATUSES[group.status]
  const closed = group.status === 'closed'

  async function toggleClosed() {
    if (!closed) {
      const ok = await confirm({
        title: t('Закрыть «{name}»?', { name: group.name }),
        message: t('Группа перестанет набирать и пропадёт из выбора. Состав и история сохранятся, группу можно вернуть.'),
        confirmText: t('Закрыть группу'),
        danger: true,
      })
      if (!ok) return
    }
    try {
      await api.patch(`groups/${group.id}/`, { status: closed ? 'active' : 'closed' })
      toast.success(closed ? t('Группа снова набирает') : t('Группа закрыта'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  async function remove(member) {
    const ok = await confirm({
      title: t('Убрать {name} из группы?', { name: member.child_name }),
      message: t('Запись останется в истории группы с сегодняшней датой выхода.'),
      confirmText: t('Убрать'),
      danger: true,
    })
    if (!ok) return
    try {
      await api.post(`groups/${group.id}/remove_member/`, { child_id: member.child })
      toast.success(t('Ребёнок убран из группы'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const full = group.members_count >= group.capacity

  return (
    <div>
      <PageHeader
        back={back}
        title={
          <span className="flex items-center gap-3">
            <span className="size-3.5 shrink-0 rounded-full" style={{ backgroundColor: group.direction_color || '#9aa3ad' }} />
            {group.name}
          </span>
        }
        description={[group.direction_name, group.branch_name, group.age_min != null && group.age_max != null ? t('{from}–{to} лет', { from: group.age_min, to: group.age_max }) : null].filter(Boolean).join(' · ')}
        actions={canManage && (
          <>
            <Button icon={Pencil} onClick={() => setEditing(true)}>{t('Редактировать')}</Button>
            <Button variant={closed ? 'secondary' : 'danger-ghost'} icon={closed ? ArchiveRestore : Lock} onClick={toggleClosed}>
              {closed ? t('Вернуть в набор') : t('Закрыть')}
            </Button>
          </>
        )}
      />

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <p className="text-[15px] font-bold text-ink">{t('Заполняемость')}</p>
            {group.status !== 'active' ? <Badge tone={groupStatus.tone}>{groupStatus.label}</Badge>
              : full ? <Badge tone="danger">{t('Мест нет')}</Badge>
                : group.is_underfilled ? <Badge tone="warning">{t('Недобор')}</Badge> : <Badge tone="success">{t('Норма')}</Badge>}
          </div>
          <FillBar group={group} />
          <p className="mt-2 text-[13px] text-ink-muted">
            {full ? t('Свободных мест нет') : t('Свободно: {count}', { count: `${group.capacity - group.members_count} ${plural(group.capacity - group.members_count, ['место', 'места', 'мест'])}` })}
          </p>
        </Card>
        <Card>
          <p className="mb-3 text-[15px] font-bold text-ink">{t('Расписание')}</p>
          {group.schedule.length ? (
            <ul className="space-y-2">
              {group.schedule.map(slot => (
                <li key={`${slot.weekday}-${slot.start_time}`} className="flex items-center gap-3 text-sm">
                  <span className="flex w-9 justify-center rounded-md bg-brand-50 py-1 text-xs font-bold text-brand-700" title={t(WEEKDAYS_FULL[slot.weekday])}>{t(WEEKDAYS_SHORT[slot.weekday])}</span>
                  <span className="font-semibold text-ink">{slot.start_time}</span>
                  <span className="text-ink-muted">{slot.duration_minutes} {t('мин')}</span>
                  {slot.room && <span className="ml-auto flex items-center gap-1 text-[13px] text-ink-subtle"><DoorOpen className="size-3.5" />{slot.room}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="flex items-center gap-2 text-sm text-ink-subtle"><CalendarClock className="size-4" /> {t('Расписание не задано')}</p>
          )}
        </Card>
        <Card>
          <p className="mb-3 text-[15px] font-bold text-ink">{t('Преподаватели')}</p>
          {group.teachers_detail.length ? (
            <ul className="space-y-2.5">
              {group.teachers_detail.map(tch => (
                <li key={tch.id} className="flex items-center gap-3 text-sm font-medium text-ink"><Avatar name={tch.full_name} />{tch.full_name}</li>
              ))}
            </ul>
          ) : <p className="text-sm text-ink-subtle">{t('Не назначены')}</p>}
        </Card>
      </div>

      <Tabs
        className="mb-4"
        tabs={[{ key: 'members', label: t('Состав'), count: members.length }, { key: 'history', label: t('История'), count: history.length }]}
        value={tab}
        onChange={key => setParams(key === 'members' ? {} : { tab: key }, { replace: true })}
      />

      {tab === 'members' ? (
        <Card padded={false}>
          <CardHeader
            className="mb-0 px-5 pt-5"
            title={`${members.length} ${plural(members.length, ['ребёнок', 'ребёнка', 'детей'])}`}
            actions={canManage && !closed && (
              <Button size="sm" icon={UserPlus} disabled={full} onClick={() => setAdding(true)} title={full ? t('В группе нет мест') : undefined}>
                {t('Добавить ребёнка')}
              </Button>
            )}
          />
          {members.length === 0 ? (
            <EmptyState icon={UsersRound} title={t('В группе пока никого')} description={t('Добавьте детей — они появятся в журнале посещений.')} />
          ) : (
            <ul className="mt-3 divide-y divide-line border-t border-line">
              {members.map(member => {
                const childStatus = CHILD_STATUSES[member.child_status]
                return (
                  <li key={member.id} className="flex items-center gap-3 px-5 py-3">
                    <Avatar name={member.child_name} />
                    <div className="min-w-0 flex-1">
                      <Link to={`/children/${member.child}`} className="font-semibold text-ink hover:text-brand-700">{member.child_name}</Link>
                      <p className="text-[13px] text-ink-muted">{ageLabel(member.child_age)} {t('· в группе с')} {formatDate(member.joined_at)}</p>
                    </div>
                    {member.child_status !== 'active' && childStatus && <Badge tone={childStatus.tone}>{childStatus.label}</Badge>}
                    {canManage && (
                      <Button variant="ghost" size="icon" aria-label={t('Убрать {name}', { name: member.child_name })} onClick={() => remove(member)}>
                        <UserMinus className="size-4" />
                      </Button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      ) : (
        <Card padded={false}>
          <ul className="divide-y divide-line">
            {history.map(entry => (
              <li key={entry.id} className="flex items-center gap-3 px-5 py-3 text-sm">
                <span className={cn('size-2 shrink-0 rounded-full', entry.left_at ? 'bg-line-strong' : 'bg-success-600')} />
                <Link to={`/children/${entry.child}`} className="min-w-0 flex-1 truncate font-medium text-ink hover:text-brand-700">{entry.child_name}</Link>
                <span className="whitespace-nowrap text-ink-muted">
                  {formatDate(entry.joined_at)} — {entry.left_at ? formatDate(entry.left_at) : <span className="text-success-600">{t('сейчас')}</span>}
                </span>
              </li>
            ))}
            {history.length === 0 && <li className="px-5 py-6 text-center text-sm text-ink-muted">{t('История пуста.')}</li>}
          </ul>
        </Card>
      )}

      {editing && <GroupModal group={group} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); load() }} />}
      {adding && (
        <AddMemberModal
          group={group}
          memberIds={members.map(m => String(m.child))}
          onClose={() => setAdding(false)}
          onAdded={() => { setAdding(false); load() }}
        />
      )}
    </div>
  )
}

/** Поиск ребёнка по имени и запись в группу; подходит ли по возрасту — видно сразу. */
function AddMemberModal({ group, memberIds, onClose, onAdded }) {
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [found, setFound] = useState(null)
  const [savingId, setSavingId] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    api.get('clients/children/table/', { params: { q: query || undefined, status: 'active', page_size: 20 }, signal: controller.signal })
      .then(r => setFound(r.data.results))
      .catch(() => {})
    return () => controller.abort()
  }, [query])

  async function add(child) {
    setSavingId(child.id)
    try {
      await api.post(`groups/${group.id}/add_member/`, { child: child.id })
      toast.success(t('{name} в группе', { name: child.full_name }))
      onAdded()
    } catch (err) {
      const data = err.response?.data
      toast.error(data?.group?.[0] || data?.child?.[0] || apiErrorMessage(err))
      setSavingId(null)
    }
  }

  const fits = age => (group.age_min == null || age >= group.age_min) && (group.age_max == null || age <= group.age_max)

  return (
    <Modal open onClose={onClose} title={t('Добавить в «{name}»', { name: group.name })} description={t('Свободно мест: {n}', { n: group.capacity - group.members_count })}>
      <SearchInput value={query} onChange={setQuery} placeholder={t('Имя ребёнка')} />
      <ul className="mt-3 max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
        {!found && <li className="px-4 py-3 text-sm text-ink-muted">{t('Загрузка…')}</li>}
        {found?.length === 0 && <li className="px-4 py-3 text-sm text-ink-muted">{t('Никого не нашли')}</li>}
        {found?.map(child => {
          const inGroup = memberIds.includes(String(child.id))
          return (
            <li key={child.id} className="flex items-center gap-3 px-4 py-2.5">
              <Avatar name={child.full_name} src={child.photo_url} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-ink">{child.full_name}</p>
                <p className="truncate text-xs text-ink-muted">
                  {ageLabel(child.age)}
                  {!fits(child.age) && <span className="text-warning-600"> {t('· не по возрасту группы')}</span>}
                  {child.group_names !== '—' && ` · ${child.group_names}`}
                </p>
              </div>
              {inGroup ? <Badge>{t('Уже в группе')}</Badge> : (
                <Button size="sm" loading={savingId === child.id} disabled={Boolean(savingId)} onClick={() => add(child)}>{t('Добавить')}</Button>
              )}
            </li>
          )
        })}
      </ul>
    </Modal>
  )
}
