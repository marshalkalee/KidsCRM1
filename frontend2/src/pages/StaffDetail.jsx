import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { MapPin, Phone, SearchX, UsersRound } from 'lucide-react'
import api from '../api/axios'
import { ROLE_LABELS } from '../session/SessionContext'
import { Avatar, Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton } from '../ui'
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
        </Card>

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
      </div>
    </div>
  )
}
