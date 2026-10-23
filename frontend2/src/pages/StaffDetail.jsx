import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { CalendarOff, KeyRound, MapPin, Phone, RotateCcw, SearchX, UsersRound } from 'lucide-react'
import api from '../api/axios'
import { ROLE_LABELS, useSession } from '../session/SessionContext'
import { Avatar, Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton, apiErrorMessage, cn, useToast } from '../ui'
import { t } from '../i18n'

const listOf = response => response.data.results || response.data

function formatPhone(phone = '') {
  const match = /^\+7(\d{3})(\d{3})(\d{2})(\d{2})$/.exec(phone)
  return match ? `+7 ${match[1]} ${match[2]} ${match[3]} ${match[4]}` : phone
}

/** Общая карточка сотрудника; личные настройки и пароль остаются только в /profile. */
export default function StaffDetail() {
  const { id } = useParams()
  const location = useLocation()
  const { can } = useSession()
  const [data, setData] = useState(null)
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      api.get(`users/${id}/`, { signal: controller.signal }),
      api.get('branches/', { signal: controller.signal }),
      api.get('groups/', { params: { teacher: id, page_size: 100 }, signal: controller.signal }),
    ])
      .then(([staff, branches, groups]) => {
        setData({ staff: staff.data, branches: listOf(branches), groups: listOf(groups) })
        setStatus('ready')
      })
      .catch(error => {
        if (error.code !== 'ERR_CANCELED') setStatus(error.response?.status === 404 ? 'missing' : 'error')
      })
    return () => controller.abort()
  }, [id])

  const back = {
    to: location.state?.from || '/groups',
    label: location.state?.label || t('Группы'),
  }
  if (status === 'loading') return <><PageHeader back={back} title={<Skeleton className="h-8 w-52" />} /><Skeleton className="h-72" /></>
  if (status === 'missing') return <Card><EmptyState icon={SearchX} title={t('Сотрудник не найден')} /></Card>
  if (status === 'error') return <Card><ErrorState /></Card>

  const { staff, branches, groups } = data
  const branchNames = branches.filter(branch => (staff.branches || []).map(String).includes(String(branch.id))).map(branch => branch.name)
  const allBranches = staff.role === 'owner' || branchNames.length === 0

  return (
    <div>
      <PageHeader
        back={back}
        title={staff.full_name}
        description={ROLE_LABELS[staff.role] || staff.role}
        actions={<Badge tone={staff.is_active ? 'success' : 'neutral'} dot>{staff.is_active ? t('Активен') : t('Отключён')}</Badge>}
      />

      <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="flex flex-col items-center text-center">
          <Avatar name={staff.full_name} src={staff.photo_url} size="lg" className="size-24 text-2xl" />
          <h2 className="mt-4 text-xl font-bold text-ink">{staff.full_name}</h2>
          <Badge className="mt-2" tone="brand">{ROLE_LABELS[staff.role] || staff.role}</Badge>

          <div className="mt-6 w-full space-y-3 border-t border-line pt-5 text-left">
            <a href={`tel:${staff.phone}`} className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm text-ink hover:bg-brand-50 hover:text-brand-700">
              <Phone className="size-4 shrink-0 text-brand-500" />
              <span>{formatPhone(staff.phone)}</span>
            </a>
            <div className="flex items-start gap-3 px-2 py-2 text-sm text-ink">
              <MapPin className="mt-0.5 size-4 shrink-0 text-brand-500" />
              <span>{allBranches ? t('Все филиалы') : branchNames.join(', ')}</span>
            </div>
          </div>
          <UpcomingAbsences staffId={staff.id} />
        </Card>

        <div className="min-w-0 space-y-5">
        <Card>
          <div className="mb-4 flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><UsersRound className="size-5" /></span>
            <div>
              <h2 className="font-bold text-ink">{t('Группы преподавателя')}</h2>
              <p className="text-xs text-ink-muted">{t('Группы, в которых сотрудник назначен преподавателем')}</p>
            </div>
          </div>
          {groups.length ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {groups.map(group => (
                <Link key={group.id} to={`/groups/${group.id}`} className="rounded-xl border border-line bg-canvas p-4 transition hover:border-brand-300 hover:bg-brand-50">
                  <div className="flex items-center gap-2">
                    <span className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: group.direction_color || '#9aa3ad' }} />
                    <span className="truncate font-semibold text-ink">{group.name}</span>
                  </div>
                  <p className="mt-2 truncate text-xs text-ink-muted">{[group.direction_name, group.branch_name].filter(Boolean).join(' · ')}</p>
                  <p className="mt-3 text-xs font-semibold text-brand-600">{group.members_count}/{group.capacity} {t('учеников')}</p>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState icon={UsersRound} title={t('Преподаватель пока не назначен ни в одну группу')} className="py-10" />
          )}
        </Card>
        {can('can_manage_staff') && <AccessCard staff={staff} />}
        </div>
      </div>
    </div>
  )
}

const ABSENCE_TONES = { vacation: 'info', sick: 'danger', day_off: 'warning', other: 'neutral' }
const shortDate = value => `${value.slice(8, 10)}.${value.slice(5, 7)}`

/** TRU-182: ближайшие отпуска, больничные и отгулы сотрудника. */
function UpcomingAbsences({ staffId }) {
  const [items, setItems] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    const now = new Date()
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    api.get('schedule/absences/', { params: { staff: staffId, date_from: today }, signal: controller.signal })
      .then(res => setItems(listOf(res).slice(0, 5)))
      .catch(() => setItems([]))
    return () => controller.abort()
  }, [staffId])

  if (!items?.length) return null
  return (
    <div className="mt-4 w-full border-t border-line pt-4 text-left">
      <p className="mb-2 flex items-center gap-2 px-2 text-[12px] font-bold uppercase tracking-wide text-ink-subtle">
        <CalendarOff className="size-3.5" />{t('Ближайшие отсутствия')}
      </p>
      <ul className="space-y-1.5">
        {items.map(item => (
          <li key={item.id} className="flex items-center justify-between gap-2 px-2 text-[13px] text-ink">
            <span>{item.starts_on === item.ends_on ? shortDate(item.starts_on) : `${shortDate(item.starts_on)} – ${shortDate(item.ends_on)}`}</span>
            <Badge tone={ABSENCE_TONES[item.kind] || 'neutral'}>{t(item.kind_display)}</Badge>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Доступ сотрудника: права роли и особые права поверх неё. Меняет только
 * владелец (сервер проверяет то же); управляющий видит, но не меняет.
 */
function AccessCard({ staff }) {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(null)
  const url = `users/${staff.id}/access/`

  useEffect(() => {
    let alive = true
    api.get(url).then(res => { if (alive) setData(res.data) }).catch(() => { if (alive) setData(false) })
    return () => { alive = false }
  }, [url])

  async function save(key, value) {
    setBusy(key)
    try {
      const res = await api.put(url, { overrides: { [key]: value } })
      setData(res.data)
      toast.success(t('Доступ сохранён'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  if (data === false) return null
  const changed = data?.items.filter(item => item.override !== null).length || 0
  return (
    <Card>
      <div className="mb-4 flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><KeyRound className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="font-bold text-ink">{t('Доступ')}</h2>
          <p className="text-xs text-ink-muted">
            {staff.role === 'owner'
              ? t('У владельца все права.')
              : t('Основу даёт роль «{role}». Отдельному сотруднику можно открыть или закрыть разделы ниже.', { role: ROLE_LABELS[staff.role] || staff.role })}
          </p>
        </div>
        {changed > 0 && <Badge tone="warning">{t('Особых прав: {n}', { n: changed })}</Badge>}
      </div>
      {!data ? <Skeleton className="h-48" /> : staff.role !== 'owner' && (
        <>
          <ul className="divide-y divide-line">
            {data.items.map(item => (
              <li key={item.key} className="flex items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-ink">
                    {t(item.label)}
                    {item.override !== null && (
                      <Badge tone={item.override ? 'success' : 'danger'}>{item.override ? t('Открыто особо') : t('Закрыто особо')}</Badge>
                    )}
                  </p>
                  <p className="text-[12px] text-ink-muted">
                    {t(item.hint)}
                    {item.override !== null && ` ${item.role_default ? t('По роли — есть.') : t('По роли — нет.')}`}
                  </p>
                </div>
                {data.editable && item.override !== null && (
                  <button
                    type="button"
                    onClick={() => save(item.key, null)}
                    disabled={busy !== null}
                    title={t('Как у роли')}
                    aria-label={t('Вернуть как у роли: {name}', { name: t(item.label) })}
                    className="flex size-8 shrink-0 items-center justify-center rounded-md text-ink-subtle hover:bg-surface-muted hover:text-ink"
                  >
                    <RotateCcw className="size-4" />
                  </button>
                )}
                <button
                  type="button"
                  role="switch"
                  aria-checked={item.effective}
                  aria-label={t(item.label)}
                  disabled={!data.editable || busy !== null}
                  onClick={() => save(item.key, !item.effective)}
                  className={cn(
                    'relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed',
                    item.effective ? 'bg-brand-500' : 'bg-[#d1d5db]',
                    !data.editable && 'opacity-60',
                  )}
                >
                  <span className={cn('absolute top-0.5 size-5 rounded-full bg-white shadow transition-all', item.effective ? 'left-[22px]' : 'left-0.5')} />
                </button>
              </li>
            ))}
          </ul>
          {!data.editable && <p className="mt-3 text-[12px] text-ink-subtle">{t('Менять доступ может только владелец центра.')}</p>}
          <p className="mt-3 text-[12px] text-ink-subtle">{t('Сотрудники, настройки центра, финансовые отчёты и справочники — только по роли.')}</p>
        </>
      )}
    </Card>
  )
}
