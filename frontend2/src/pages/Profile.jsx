import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Building2, Camera, Check, Eye, EyeOff, Info, Loader2, Lock, LogOut, MapPin, Shield, Trash2, User } from 'lucide-react'
import api from '../api/axios'
import { useSession } from '../session/SessionContext'
import { Button, Field, Input, apiErrorMessage, cn, formatPhone, initials, useConfirm, useToast } from '../ui'
import { t } from '../i18n'

const TABS = [
  { key: 'data', icon: User, get title() { return t('Личные данные') }, get hint() { return t('ФИО, телефон, филиалы') } },
  { key: 'password', icon: Lock, get title() { return t('Пароль') }, get hint() { return t('Сменить пароль') } },
  { key: 'security', icon: Shield, get title() { return t('Безопасность') }, get hint() { return t('Выход с устройств') } },
]

/** Профиль сотрудника: своё ФИО, пароль и выход на всех устройствах. */
export default function Profile() {
  const { user, roleLabel } = useSession()
  const [params, setParams] = useSearchParams()
  const tab = TABS.some(item => item.key === params.get('tab')) ? params.get('tab') : 'data'
  const open = key => setParams(key === 'data' ? {} : { tab: key }, { replace: true })

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface md:min-h-[620px] md:flex-row">
      <nav className="flex shrink-0 flex-col border-b border-line md:w-[280px] md:border-r md:border-b-0">
        <div className="flex flex-col items-center gap-3 border-b border-brand-100 bg-brand-50/60 px-5 pt-7 pb-6 text-center">
          <ProfilePhoto />
          <div className="flex flex-col items-center gap-1.5">
            <p className="text-[17px] font-semibold text-ink">{user?.full_name}</p>
            <span className="rounded-full border border-brand-200 bg-surface px-2.5 py-0.5 text-xs font-semibold text-brand-700">{roleLabel}</span>
          </div>
          {user?.organization_name && <p className="text-[13px] text-ink-muted">{user.organization_name}</p>}
        </div>
        <div role="tablist" aria-orientation="vertical" className="grid grid-cols-3 gap-1.5 p-3 md:flex md:flex-col">
          {TABS.map(item => {
            const active = item.key === tab
            const Icon = item.icon
            return (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => open(item.key)}
                className={cn(
                  'flex flex-col items-center gap-2 rounded-lg border px-2 py-2.5 text-center transition md:flex-row md:gap-3 md:px-3 md:text-left',
                  active ? 'border-brand-200 bg-surface shadow-[0_4px_12px_rgb(228_88_110/0.12)]' : 'border-transparent hover:bg-surface-muted',
                )}
              >
                <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-md', active ? 'bg-brand-gradient text-white' : 'bg-canvas text-ink-muted')}>
                  <Icon className="size-[18px]" />
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className={cn('text-[13px] md:text-sm', active ? 'font-semibold text-ink' : 'font-medium text-ink-muted')}>{item.title}</span>
                  <span className="hidden text-xs text-ink-subtle md:block">{item.hint}</span>
                </span>
              </button>
            )
          })}
        </div>
      </nav>

      <div className="min-w-0 flex-1 px-5 py-6 sm:px-10 sm:py-8">
        <div className="max-w-[600px]">
          {tab === 'data' && <PersonalData />}
          {tab === 'password' && <PasswordForm />}
          {tab === 'security' && <Security onChangePassword={() => open('password')} />}
        </div>
      </div>
    </div>
  )
}

/** Своё фото: кнопка-камера на аватаре, файл уходит сразу при выборе. */
function ProfilePhoto() {
  const { user, updateUser } = useSession()
  const toast = useToast()
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const photo = user?.photo_url

  async function send(request) {
    setBusy(true)
    try {
      const { data } = await request()
      updateUser(data)
    } catch (err) {
      toast.error(err.response?.data?.file?.[0] || apiErrorMessage(err))
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const upload = file => {
    if (!file) return
    const body = new FormData()
    body.append('file', file)
    send(() => api.post('users/auth/me/photo/', body))
  }

  return (
    <div className="flex flex-col items-center gap-3.5">
      <div className="relative">
        <span className="bg-brand-gradient flex size-[84px] items-center justify-center overflow-hidden rounded-full text-[28px] font-bold text-white shadow-[0_0_0_4px_#fff,0_8px_20px_rgb(228_88_110/0.28)]">
          {photo ? <img src={photo} alt="" className="size-full object-cover" /> : initials(user?.full_name)}
          {busy && (
            <span className="absolute inset-0 flex items-center justify-center rounded-full bg-ink/40">
              <Loader2 className="size-6 animate-spin text-white" />
            </span>
          )}
        </span>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="absolute -right-1 -bottom-1 flex size-8 items-center justify-center rounded-full border-2 border-white bg-surface text-brand-600 shadow-md transition hover:bg-brand-50 disabled:opacity-60"
          aria-label={photo ? t('Заменить фото') : t('Загрузить фото')}
          title={photo ? t('Заменить фото') : t('Загрузить фото')}
        >
          <Camera className="size-4" />
        </button>
      </div>
      {photo ? (
        <button
          type="button"
          onClick={() => send(() => api.delete('users/auth/me/photo/'))}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded px-1 text-xs font-semibold text-ink-subtle transition-colors hover:text-danger-600 disabled:opacity-60"
        >
          <Trash2 className="size-3.5" />
          {t('Удалить фото')}
        </button>
      ) : (
        <p className="text-[11px] text-ink-subtle">{t('JPG, PNG до 5 МБ')}</p>
      )}
      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={e => upload(e.target.files[0])} />
    </div>
  )
}

function SectionTitle({ title, description }) {
  return (
    <div className="mb-6">
      <h2 className="text-xl font-semibold text-ink">{title}</h2>
      <p className="mt-1 text-sm text-ink-muted">{description}</p>
    </div>
  )
}

function PersonalData() {
  const { user, branches, updateUser } = useSession()
  const toast = useToast()
  const [name, setName] = useState(user?.full_name || '')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const changed = name.trim() !== (user?.full_name || '')

  // Владелец и сотрудник без закреплённых филиалов видят все (как в API).
  const myBranches = user?.role !== 'owner' && user?.branches?.length
    ? branches.filter(b => user.branches.includes(String(b.id))).map(b => b.name).join(', ')
    : t('Все филиалы')

  const save = async event => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const { data } = await api.patch('users/auth/me/', { full_name: name })
      updateUser(data)
      setName(data.full_name)
      toast.success(t('Сохранено'))
    } catch (err) {
      setError(err.response?.data?.full_name || apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={save}>
      <SectionTitle title={t('Личные данные')} description={t('Так вас видят коллеги в журнале, заявках и истории изменений.')} />
      <div className="flex flex-col gap-5">
        <Field label={t('ФИО')} error={error} required>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} value={name} onChange={e => setName(e.target.value)} autoComplete="name" maxLength={255} />
          )}
        </Field>
        <Field label={t('Телефон для входа')} hint={t('Это ваш логин. Сменить номер может владелец центра.')}>
          <div className="font-btn flex h-[38px] items-center gap-2.5 rounded-md border-[1.5px] border-dashed border-line-strong bg-surface-muted px-3 text-[13px] text-ink-muted">
            <Lock className="size-4 shrink-0" />
            {formatPhone(user?.phone)}
          </div>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <InfoTile icon={Building2} tone="bg-info-50 text-info-600" label={t('Центр')} value={user?.organization_name || '—'} />
          <InfoTile icon={MapPin} tone="bg-success-50 text-success-600" label={t('Мои филиалы')} value={myBranches || '—'} />
        </div>
        <div className="flex justify-end border-t border-line pt-5">
          <Button type="submit" variant="primary" loading={saving} disabled={!changed}>{t('Сохранить')}</Button>
        </div>
      </div>
    </form>
  )
}

function InfoTile({ icon: Icon, tone, label, value }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line bg-canvas px-4 py-3.5">
      <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-md', tone)}>
        <Icon className="size-[18px]" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="text-xs text-ink-muted">{label}</span>
        <span className="truncate text-sm font-medium text-ink" title={value}>{value}</span>
      </span>
    </div>
  )
}

function PasswordInput({ id, invalid, value, onChange, autoComplete }) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Input id={id} invalid={invalid} type={visible ? 'text' : 'password'} value={value} onChange={onChange} autoComplete={autoComplete} className="pr-10" />
      <button
        type="button"
        onClick={() => setVisible(v => !v)}
        className="absolute inset-y-0 right-1 my-auto flex size-8 items-center justify-center rounded text-ink-subtle hover:text-ink"
        aria-label={visible ? t('Скрыть пароль') : t('Показать пароль')}
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}

// Подсказка для человека, а не проверка: правила пароля проверяет сервер.
function strength(password) {
  if (!password) return 0
  let score = password.length >= 8 ? 1 : 0
  if (password.length >= 12) score += 1
  if (/\d/.test(password) && /\D/.test(password)) score += 1
  if (/[^\p{L}\d]/u.test(password) || (/\p{Lu}/u.test(password) && /\p{Ll}/u.test(password))) score += 1
  return Math.max(score, 1)
}

const STRENGTH = [
  null,
  { get label() { return t('Слабый пароль') }, bar: 'bg-danger-600', text: 'text-danger-600' },
  { get label() { return t('Так себе') }, bar: 'bg-warning-600', text: 'text-warning-600' },
  { get label() { return t('Хороший пароль') }, bar: 'bg-success-600', text: 'text-success-600' },
  { get label() { return t('Надёжный пароль') }, bar: 'bg-success-600', text: 'text-success-600' },
]

function PasswordForm() {
  const toast = useToast()
  const [form, setForm] = useState({ old_password: '', new_password: '', repeat: '' })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }))

  const score = strength(form.new_password)
  const level = STRENGTH[score]
  const longEnough = form.new_password.length >= 8
  const notDigits = /\D/.test(form.new_password)
  const matches = form.repeat !== '' && form.repeat === form.new_password
  const ready = form.old_password && longEnough && notDigits && matches

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      await api.post('users/auth/change-password/', { old_password: form.old_password, new_password: form.new_password })
      setForm({ old_password: '', new_password: '', repeat: '' })
      toast.success(t('Пароль изменён'))
    } catch (err) {
      const data = err.response?.data || {}
      if (data.old_password || data.new_password) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <SectionTitle title={t('Пароль')} description={t('После смены на этом устройстве вы останетесь в системе.')} />
      <div className="flex flex-col gap-5">
        <Field label={t('Текущий пароль')} error={errors.old_password} required>
          {({ id, invalid }) => <PasswordInput id={id} invalid={invalid} value={form.old_password} onChange={set('old_password')} autoComplete="current-password" />}
        </Field>
        <div className="flex flex-col gap-2.5">
          <Field label={t('Новый пароль')} error={errors.new_password} required>
            {({ id, invalid }) => <PasswordInput id={id} invalid={invalid} value={form.new_password} onChange={set('new_password')} autoComplete="new-password" />}
          </Field>
          <div className="grid grid-cols-4 gap-1.5" aria-hidden="true">
            {[1, 2, 3, 4].map(step => (
              <span key={step} className={cn('h-1.5 rounded-full', step <= score ? level.bar : 'bg-line')} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {level && <span className={cn('font-semibold', level.text)}>{level.label}</span>}
            <Rule ok={longEnough}>{t('8 символов и больше')}</Rule>
            <Rule ok={form.new_password !== '' && notDigits}>{t('не только цифры')}</Rule>
          </div>
        </div>
        <Field
          label={t('Повторите новый пароль')}
          error={form.repeat && !matches ? t('Пароли не совпадают') : null}
          required
        >
          {({ id, invalid }) => <PasswordInput id={id} invalid={invalid} value={form.repeat} onChange={set('repeat')} autoComplete="new-password" />}
        </Field>
        <div className="flex justify-end border-t border-line pt-5">
          <Button type="submit" variant="primary" loading={saving} disabled={!ready}>{t('Сменить пароль')}</Button>
        </div>
      </div>
    </form>
  )
}

function Rule({ ok, children }) {
  return (
    <span className={cn('inline-flex items-center gap-1', ok ? 'text-success-600' : 'text-ink-subtle')}>
      <Check className="size-3.5" />
      {children}
    </span>
  )
}

function Security({ onChangePassword }) {
  const { logout } = useSession()
  const confirm = useConfirm()
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  const logoutEverywhere = async () => {
    const ok = await confirm({
      title: t('Выйти на всех устройствах?'),
      message: t('Вход закроется везде, и на этом устройстве тоже.'),
      confirmText: t('Выйти везде'),
      danger: true,
    })
    if (!ok) return
    setBusy(true)
    try {
      await api.post('users/auth/logout-all/')
      await logout()
    } catch (err) {
      toast.error(apiErrorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div>
      <SectionTitle title={t('Безопасность')} description={t('Если заходили с чужого компьютера или потеряли телефон.')} />
      <div className="flex flex-col gap-5">
        <div className="rounded-xl border border-danger-50 bg-danger-50/40 p-5 sm:p-6">
          <div className="flex items-start gap-3.5">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-danger-50 text-danger-600">
              <LogOut className="size-5" />
            </span>
            <div className="min-w-0">
              <p className="text-base font-semibold text-ink">{t('Выйти на всех устройствах')}</p>
              <p className="mt-1 text-sm text-ink-muted">{t('Что произойдёт:')}</p>
              <ol className="mt-3 flex list-decimal flex-col gap-2 pl-5 text-sm leading-relaxed text-ink">
                <li>{t('Вход закроется на всех телефонах и компьютерах — и на этом тоже.')}</li>
                <li>{t('Чтобы вернуться, войдите заново по телефону и паролю.')}</li>
                <li>{t('Отметки, заявки и всё, что вы сохранили, останутся на месте.')}</li>
              </ol>
              <Button variant="danger" icon={LogOut} loading={busy} onClick={logoutEverywhere} className="mt-5">
                {t('Выйти везде')}
              </Button>
            </div>
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-lg border border-line bg-canvas px-4 py-3.5 text-sm text-ink">
          <Info className="mt-0.5 size-[18px] shrink-0 text-info-600" />
          <span>
            {t('Думаете, пароль знает кто-то ещё? Сначала смените пароль, потом выйдите везде.')}{' '}
            <button type="button" onClick={onChangePassword} className="font-semibold text-brand-600 hover:underline">
              {t('Сменить пароль')}
            </button>
          </span>
        </div>
      </div>
    </div>
  )
}
