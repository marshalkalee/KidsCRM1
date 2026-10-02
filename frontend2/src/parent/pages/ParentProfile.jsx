import { useState } from 'react'
import { Baby, Building2, LogOut, Monitor, Smartphone } from 'lucide-react'
import {
  Avatar,
  Badge,
  Button,
  CHILD_STATUSES,
  Card,
  CardHeader,
  Field,
  Input,
  Modal,
  PageHeader,
  Skeleton,
  ageLabel,
  cn,
  formatDate,
  formatDateTime,
  formatPhone,
  useToast,
} from '../../ui'
import { LANGUAGES, lang, setLang, t } from '../../i18n'
import { phoneDigits, phoneInputProps } from '../../utils/formValidation'
import portal, { portalError, usePortalData } from '../api'
import { useParent } from '../useParent'

/*
 * Профиль родителя (TRU-136): контакты, язык кабинета, смена номера через
 * код на новый номер, устройства и выход. Данные ребёнка здесь не
 * меняются — только через администратора (docs/parent-portal.md).
 */

const ERRORS = {
  get offline() { return t('Нет связи. Попробуйте позже.') },
  get other() { return t('Не получилось сохранить.') },
}
const PORTAL_LANGUAGES = LANGUAGES.filter(l => l.code === 'ru' || l.code === 'kk')

export default function ParentProfile() {
  const { profile, children, child, selectChild, me, signOut } = useParent()
  const toast = useToast()
  const [email, setEmail] = useState(null)
  const [saving, setSaving] = useState(false)
  const [changingPhone, setChangingPhone] = useState(false)

  if (!profile) return <Skeleton className="h-64" />
  const shownEmail = email ?? profile.email

  async function saveEmail(event) {
    event.preventDefault()
    setSaving(true)
    try {
      await portal.patch('profile/', { email: shownEmail })
      toast.success(t('Сохранено'))
      me.reload()
    } catch (err) {
      toast.error(portalError(err, ERRORS))
    } finally {
      setSaving(false)
    }
  }

  async function changeLanguage(code) {
    setLang(code)
    try {
      await portal.patch('profile/', { language: code })
      me.reload()
    } catch { /* язык уже сменился на этом телефоне; на сервере — при следующем разе */ }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title={t('Профиль')}
        description={t('Контактные данные родителя и информация о связанных детях.')}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.8fr)_minmax(0,1.2fr)]">
        <Card>
          <CardHeader title={t('Профиль родителя')} />
          <div className="flex items-center gap-3">
            <Avatar name={profile.full_name || t('Родитель')} size="lg" />
            <div className="min-w-0">
              <p className="truncate text-lg font-bold text-ink">{profile.full_name || t('Родитель')}</p>
              <p className="mt-0.5 text-sm text-ink-muted">{formatPhone(profile.phone)}</p>
            </div>
          </div>
          {profile.centers?.length > 0 && (
            <p className="mt-4 flex items-center gap-2 rounded-lg bg-surface-muted px-3 py-2.5 text-[13px] text-ink-muted">
              <Building2 className="size-4 shrink-0" />{profile.centers.join(' · ')}
            </p>
          )}
          <Button size="sm" className="mt-4" onClick={() => setChangingPhone(true)}>{t('Сменить номер')}</Button>
        </Card>

        <ChildrenCard childOptions={children} selected={child} onSelect={selectChild} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title={t('Почта')} description={t('Центр может присылать на неё документы.')} />
          <form onSubmit={saveEmail} className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <Field label={t('Email')} className="flex-1">
              {({ id }) => <Input id={id} type="email" value={shownEmail} onChange={e => setEmail(e.target.value)} placeholder="name@mail.kz" autoComplete="email" />}
            </Field>
            <Button type="submit" variant="primary" loading={saving} disabled={shownEmail === profile.email}>{t('Сохранить')}</Button>
          </form>
        </Card>

        <Card>
          <CardHeader title={t('Язык кабинета')} />
          <div role="radiogroup" aria-label={t('Язык кабинета')} className="grid grid-cols-2 gap-2">
            {PORTAL_LANGUAGES.map(l => (
              <button
                key={l.code}
                type="button"
                role="radio"
                aria-checked={lang === l.code}
                onClick={() => changeLanguage(l.code)}
                className={cn('h-11 rounded-md border-[1.5px] text-sm font-semibold', lang === l.code ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line-strong text-ink-muted')}
              >
                {l.label}
              </button>
            ))}
          </div>
        </Card>
      </div>

      <Devices />

      <Card className="space-y-2">
        <Button icon={LogOut} className="w-full" onClick={() => signOut()}>{t('Выйти')}</Button>
        <Button variant="ghost" className="w-full" onClick={() => signOut({ everywhere: true })}>{t('Выйти на всех устройствах')}</Button>
      </Card>

      <p className="px-1 text-center text-[12px] text-ink-subtle">{t('Изменить данные ребёнка может администратор центра.')}</p>

      {changingPhone && <PhoneChange onClose={() => setChangingPhone(false)} onDone={() => { setChangingPhone(false); me.reload() }} />}
    </div>
  )
}

function ChildrenCard({ childOptions, selected, onSelect }) {
  return (
    <Card>
      <CardHeader
        title={t('Дети в кабинете')}
        description={t('Данные загружаются из карточки ребёнка в центре.')}
      />
      {childOptions.length ? (
        <div className="grid gap-3 md:grid-cols-2">
          {childOptions.map(item => {
            const status = CHILD_STATUSES[item.status] || { label: item.status, tone: 'neutral' }
            const isSelected = item.id === selected?.id
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelect(item.id)}
                className={cn(
                  'rounded-xl border p-4 text-left transition',
                  isSelected ? 'border-brand-300 bg-brand-50/50' : 'border-line hover:border-brand-200 hover:bg-canvas',
                )}
              >
                <div className="flex items-start gap-3">
                  <Avatar name={item.full_name} src={item.photo_url} size="lg" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate font-bold text-ink">{item.full_name}</p>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </div>
                    <p className="mt-1 text-[13px] text-ink-muted">
                      {ageLabel(item.age)} · {t('дата рождения')} {formatDate(item.birth_date)}
                    </p>
                    <p className="mt-2 flex items-center gap-1.5 text-[13px] text-ink-muted">
                      <Building2 className="size-3.5 shrink-0" />{item.organization.name}
                    </p>
                    <p className="mt-1 flex items-start gap-1.5 text-[13px] text-ink-muted">
                      <Baby className="mt-0.5 size-3.5 shrink-0" />
                      <span>{item.groups?.length
                        ? item.groups.map(group => [group.name, group.direction, group.branch].filter(Boolean).join(' · ')).join('; ')
                        : t('Группа пока не назначена')}</span>
                    </p>
                  </div>
                </div>
                {isSelected && <p className="mt-3 text-xs font-semibold text-brand-600">{t('Выбран для просмотра')}</p>}
              </button>
            )
          })}
        </div>
      ) : (
        <p className="rounded-lg bg-surface-muted px-4 py-5 text-sm text-ink-muted">{t('Связанных детей пока нет.')}</p>
      )}
    </Card>
  )
}

function deviceName(userAgent = '') {
  if (/iPhone|iPad/.test(userAgent)) return 'iPhone / iPad'
  if (/Android/.test(userAgent)) return 'Android'
  if (/Windows/.test(userAgent)) return 'Windows'
  if (/Mac OS/.test(userAgent)) return 'Mac'
  return t('Устройство')
}

function Devices() {
  const sessions = usePortalData('auth/sessions/')
  const toast = useToast()
  if (!sessions.data || sessions.data.length < 2) return null

  async function revoke(id) {
    try {
      await portal.delete(`auth/sessions/${id}/`)
      sessions.reload()
    } catch (err) {
      toast.error(portalError(err, ERRORS))
    }
  }

  return (
    <Card>
      <CardHeader title={t('Где вы вошли')} description={t('Потеряли телефон — завершите вход на нём.')} />
      <ul className="divide-y divide-line">
        {sessions.data.map(s => {
          const Icon = /iPhone|iPad|Android/.test(s.user_agent) ? Smartphone : Monitor
          return (
            <li key={s.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <Icon className="size-5 shrink-0 text-ink-muted" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-ink">{deviceName(s.user_agent)}{s.current && <span className="ml-2 text-[12px] font-normal text-success-600">{t('это устройство')}</span>}</p>
                <p className="text-[12.5px] text-ink-muted">{t('был(а) в кабинете {date}', { date: formatDateTime(s.last_seen_at) })}</p>
              </div>
              {!s.current && <Button size="sm" variant="ghost" onClick={() => revoke(s.id)}>{t('Завершить')}</Button>}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function PhoneChange({ onClose, onDone }) {
  const toast = useToast()
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { data } = await portal.post('profile/phone/', sent ? { phone, code } : { phone })
      if (sent) {
        toast.success(t('Номер изменён'))
        onDone()
      } else {
        setPhone(data.phone)
        setSent(true)
      }
    } catch (err) {
      setError(portalError(err, ERRORS))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={t('Новый номер телефона')}
      description={t('Пришлём код на новый номер — так мы убедимся, что он ваш.')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="parent-phone-form" loading={busy}>{sent ? t('Подтвердить') : t('Получить код')}</Button>
        </>
      }
    >
      <form id="parent-phone-form" onSubmit={submit} className="space-y-3">
        <Field label={t('Новый номер')} error={sent ? null : error}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={phone} disabled={sent} onChange={e => setPhone(phoneDigits(e.target.value))} required {...phoneInputProps} />}
        </Field>
        {sent && (
          <Field label={t('Код из сообщения')} error={error}>
            {({ id, invalid }) => (
              <Input id={id} invalid={invalid} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" required autoFocus className="text-center text-xl font-bold tracking-[0.3em]" />
            )}
          </Field>
        )}
      </form>
    </Modal>
  )
}
