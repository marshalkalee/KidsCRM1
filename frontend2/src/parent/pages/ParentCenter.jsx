import { AtSign, Clock, ExternalLink, MapPin, MessageCircle, Phone, UsersRound } from 'lucide-react'
import { Badge, Card, CardHeader, ErrorState, Skeleton, formatPhone } from '../../ui'
import { t } from '../../i18n'
import { hoursSummary } from '../../components/workingHours'
import { usePortalData } from '../api'
import { useParent } from '../useParent'

/*
 * «О центре» в кабинете родителя (portal/center.py): что центр рассказывает
 * о себе (профиль центра — если опубликован), филиалы с адресом, картой,
 * часами и WhatsApp — свой филиал первым — и группы ребёнка с описанием
 * «что взять с собой».
 */
export default function ParentCenter() {
  const { child } = useParent()
  const { data, loading, reload } = usePortalData(child && `children/${child.id}/center/`)
  if (!child) return null
  if (!data && loading) return <div className="space-y-3"><Skeleton className="h-56" /><Skeleton className="h-40" /></div>
  if (!data) return <Card><ErrorState onRetry={reload} /></Card>

  return (
    <div className="space-y-3">
      <About name={data.name} profile={data.profile} />
      {data.groups.length > 0 && <Groups groups={data.groups} />}
      <Branches branches={data.branches} />
    </div>
  )
}

function About({ name, profile }) {
  const photos = profile?.photo_urls || []
  return (
    <Card padded={false} className="overflow-hidden">
      {photos.length > 0 && (
        <div className="flex snap-x gap-2 overflow-x-auto p-2">
          {photos.map(url => (
            <img key={url} src={url} alt="" className="h-40 w-64 shrink-0 snap-start rounded-lg object-cover sm:h-48 sm:w-80" />
          ))}
        </div>
      )}
      <div className="p-5">
        <div className="flex items-center gap-3">
          <span className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-50 text-lg font-bold text-brand-600">
            {profile?.logo_url ? <img src={profile.logo_url} alt="" className="size-full object-cover" /> : name.slice(0, 1)}
          </span>
          <h1 className="min-w-0 text-[20px] font-bold leading-tight text-ink">{name}</h1>
        </div>
        {profile?.description && <p className="mt-3 whitespace-pre-line text-[14px] leading-relaxed text-ink">{profile.description}</p>}
        {(profile?.phone || profile?.instagram) && (
          <div className="mt-4 flex flex-wrap gap-2">
            {profile.phone && (
              <a href={`tel:${profile.phone}`} className="inline-flex h-10 items-center gap-2 rounded-md border border-line-strong px-3 text-sm font-semibold text-ink">
                <Phone className="size-4" />{formatPhone(profile.phone)}
              </a>
            )}
            {profile.whatsapp_url && (
              <a href={profile.whatsapp_url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-md bg-success-50 px-3 text-sm font-semibold text-success-600">
                <MessageCircle className="size-4" />WhatsApp
              </a>
            )}
            {profile.instagram_url && (
              <a href={profile.instagram_url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-md border border-line-strong px-3 text-sm font-semibold text-ink">
                <AtSign className="size-4" />{profile.instagram}
              </a>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

function Groups({ groups }) {
  return (
    <Card>
      <CardHeader title={t('Группы ребёнка')} description={t('Что делают на занятиях и что взять с собой.')} />
      <ul className="divide-y divide-line">
        {groups.map(group => (
          <li key={`${group.name}-${group.branch}`} className="py-3 first:pt-0 last:pb-0">
            <p className="flex items-center gap-2 text-[15px] font-semibold text-ink"><UsersRound className="size-4 text-ink-subtle" />{group.name}</p>
            <p className="text-[13px] text-ink-muted">{[group.direction, group.branch].filter(Boolean).join(' · ')}</p>
            {group.description && <p className="mt-1.5 whitespace-pre-line text-[13px] text-ink">{group.description}</p>}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Branches({ branches }) {
  if (!branches.length) return null
  return (
    <Card>
      <CardHeader title={branches.length > 1 ? t('Филиалы') : t('Филиал')} />
      <ul className="divide-y divide-line">
        {branches.map(branch => (
          <li key={branch.id} className="py-4 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[15px] font-semibold text-ink">{branch.name}</p>
              {branch.is_childs && <Badge tone="brand">{t('Здесь занимается ребёнок')}</Badge>}
            </div>
            {(branch.address || branch.city) && (
              <p className="mt-1 flex items-start gap-2 text-[13px] text-ink-muted">
                <MapPin className="mt-0.5 size-4 shrink-0" />
                <span>{[branch.city, branch.district, branch.address].filter(Boolean).join(', ')}</span>
              </p>
            )}
            <p className="mt-1 flex items-start gap-2 text-[13px] text-ink-muted">
              <Clock className="mt-0.5 size-4 shrink-0" />
              <span>{hoursSummary(branch.working_hours)}</span>
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {branch.phone && (
                <a href={`tel:${branch.phone}`} className="inline-flex h-9 items-center gap-2 rounded-md border border-line-strong px-3 text-[13px] font-semibold text-ink">
                  <Phone className="size-4" />{formatPhone(branch.phone)}
                </a>
              )}
              {branch.whatsapp_url && (
                <a href={branch.whatsapp_url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-2 rounded-md bg-success-50 px-3 text-[13px] font-semibold text-success-600">
                  <MessageCircle className="size-4" />WhatsApp
                </a>
              )}
              {branch.map_url && (
                <a href={branch.map_url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-2 rounded-md border border-line-strong px-3 text-[13px] font-semibold text-ink">
                  <ExternalLink className="size-4" />{t('На карте')}
                </a>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}
