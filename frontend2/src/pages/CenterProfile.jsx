import { useCallback, useEffect, useRef, useState } from 'react'
import { AtSign, Camera, ImagePlus, Phone, Trash2 } from 'lucide-react'
import api from '../api/axios'
import { Badge, Button, Card, CardHeader, Checkbox, ErrorState, Field, Input, PageHeader, Skeleton, Textarea, apiErrorMessage, cn, formatPhone, useToast } from '../ui'
import { t } from '../i18n'
import { phoneDigits, phoneInputProps } from '../utils/formValidation'

/*
 * Публичный профиль центра (TRU-179) — для будущего каталога кружков:
 * логотип, пара строк о центре, фото, публичные контакты. Пока не
 * опубликован, наружу не уходит ничего. Справа — как увидит родитель.
 */
export default function CenterProfile() {
  const toast = useToast()
  const [profile, setProfile] = useState(null)
  const [form, setForm] = useState(null)
  const [error, setError] = useState(false)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(null)
  const logoInput = useRef(null)
  const photoInput = useRef(null)

  const apply = data => {
    setProfile(data)
    setForm({ description: data.description, phone: phoneDigits(data.phone), instagram: data.instagram, is_published: data.is_published })
  }
  const load = useCallback(() => api.get('api-keys/center-profile/').then(res => apply(res.data)).catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  async function save(patch = form) {
    setSaving(true)
    setErrors({})
    try {
      const res = await api.patch('api-keys/center-profile/', patch)
      apply(res.data)
      toast.success(t('Профиль сохранён'))
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function upload(kind, file) {
    if (!file) return
    setUploading(kind)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await api.post(`api-keys/center-profile/${kind}/`, body)
      apply(res.data)
    } catch (err) {
      toast.error(err.response?.data?.file?.[0] || apiErrorMessage(err))
    } finally {
      setUploading(null)
    }
  }

  async function remove(kind, url) {
    try {
      const res = await api.delete(`api-keys/center-profile/${kind}/`, { data: url ? { url } : {} })
      apply(res.data)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!profile) return <Skeleton className="h-96" />
  const dirty = form.description !== profile.description || form.phone !== phoneDigits(profile.phone) || form.instagram !== profile.instagram

  return (
    <div>
      <PageHeader
        back={{ to: '/settings/organization', label: t('Организация') }}
        title={t('Профиль центра')}
        description={t('Карточка центра для будущего каталога кружков. Пока профиль не опубликован, его никто не видит.')}
      />
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-4">
          <Card>
            <CardHeader title={t('Логотип и фото')} description={t('JPG или PNG до 5 МБ. Фото — зал, занятия, выступления: до {n} штук.', { n: profile.max_photos })} />
            <div className="flex flex-wrap items-start gap-4">
              <div>
                <button type="button" onClick={() => logoInput.current?.click()} className="flex size-24 items-center justify-center overflow-hidden rounded-xl border border-dashed border-line-strong bg-surface-muted text-ink-subtle hover:border-brand-400" aria-label={t('Загрузить логотип')}>
                  {profile.logo_url ? <img src={profile.logo_url} alt="" className="size-full object-cover" /> : <Camera className="size-6" />}
                </button>
                <p className="mt-1 text-center text-[12px] text-ink-muted">{uploading === 'logo' ? t('Загрузка…') : t('Логотип')}</p>
                {profile.logo_url && <button type="button" className="mx-auto block text-[12px] font-semibold text-danger-600" onClick={() => remove('logo')}>{t('Убрать')}</button>}
                <input ref={logoInput} type="file" accept="image/png,image/jpeg" hidden onChange={e => { upload('logo', e.target.files?.[0]); e.target.value = '' }} />
              </div>
              <div className="flex flex-wrap gap-2">
                {profile.photo_urls.map(url => (
                  <div key={url} className="group relative size-24 overflow-hidden rounded-xl">
                    <img src={url} alt="" className="size-full object-cover" />
                    <button type="button" onClick={() => remove('photos', url)} className="absolute right-1 top-1 rounded-md bg-black/50 p-1 text-white" aria-label={t('Удалить фото')}><Trash2 className="size-3.5" /></button>
                  </div>
                ))}
                {profile.photo_urls.length < profile.max_photos && (
                  <button type="button" onClick={() => photoInput.current?.click()} className="flex size-24 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-line-strong text-[12px] text-ink-subtle hover:border-brand-400">
                    <ImagePlus className="size-5" />{uploading === 'photos' ? t('Загрузка…') : t('Фото')}
                  </button>
                )}
                <input ref={photoInput} type="file" accept="image/png,image/jpeg" hidden onChange={e => { upload('photos', e.target.files?.[0]); e.target.value = '' }} />
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader title={t('О центре')} />
            <div className="space-y-3">
              <Field label={t('Пара строк для родителей')} error={errors.description?.[0]} hint={t('Что за центр, для какого возраста, чем отличаетесь. До 1000 символов.')}>
                {({ id, invalid }) => <Textarea id={id} invalid={invalid} rows={5} maxLength={1000} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder={t('Балетная студия для детей 4–14 лет. Классика, растяжка, выступления дважды в год.')} />}
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={t('Телефон для родителей')} error={errors.phone?.[0]}>
                  {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.phone} onChange={e => setForm({ ...form, phone: phoneDigits(e.target.value) })} placeholder="77000000000" {...phoneInputProps} />}
                </Field>
                <Field label={t('Instagram')} error={errors.instagram?.[0]}>
                  {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.instagram} onChange={e => setForm({ ...form, instagram: e.target.value })} placeholder="@trueballet" />}
                </Field>
              </div>
              <div className="flex justify-end">
                <Button variant="primary" onClick={() => save({ description: form.description, phone: form.phone, instagram: form.instagram })} loading={saving} disabled={!dirty}>{t('Сохранить')}</Button>
              </div>
            </div>
          </Card>

          <Card>
            <Checkbox
              checked={form.is_published}
              disabled={saving}
              onChange={e => save({ is_published: e.target.checked })}
              label={<span className="text-sm font-semibold text-ink">{t('Опубликовать профиль в каталоге')}</span>}
            />
            <p className="mt-1 pl-7 text-[13px] text-ink-muted">{t('В каталог попадут только группы, которые вы отметили публичными, и цены публичных типов абонементов.')}</p>
            {errors.is_published && <p className="mt-1 pl-7 text-[13px] text-danger-600">{errors.is_published[0]}</p>}
          </Card>
        </div>

        <Preview profile={profile} />
      </div>
    </div>
  )
}

/** Как увидит родитель в каталоге. */
function Preview({ profile }) {
  return (
    <Card className="lg:sticky lg:top-24">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[12px] font-bold uppercase tracking-wider text-ink-subtle">{t('Так увидит родитель')}</p>
        {profile.is_published ? <Badge tone="success">{t('Опубликован')}</Badge> : <Badge>{t('Не опубликован')}</Badge>}
      </div>
      {profile.photo_urls[0] ? (
        <img src={profile.photo_urls[0]} alt="" className="mb-3 h-36 w-full rounded-lg object-cover" />
      ) : (
        <div className="mb-3 flex h-36 items-center justify-center rounded-lg bg-surface-muted text-[13px] text-ink-subtle">{t('Здесь будет фото')}</div>
      )}
      <div className="flex items-center gap-3">
        <span className={cn('flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-full bg-brand-50 font-bold text-brand-600')}>
          {profile.logo_url ? <img src={profile.logo_url} alt="" className="size-full object-cover" /> : profile.organization_name.slice(0, 1)}
        </span>
        <p className="min-w-0 truncate text-[15px] font-bold text-ink">{profile.organization_name}</p>
      </div>
      <p className={cn('mt-2 whitespace-pre-line text-[13px]', profile.description ? 'text-ink' : 'text-ink-subtle')}>
        {profile.description || t('Напишите пару строк о центре — без них карточка пустая.')}
      </p>
      <div className="mt-3 space-y-1 text-[13px] text-ink-muted">
        {profile.phone && <p className="flex items-center gap-2"><Phone className="size-3.5" />{formatPhone(profile.phone)}</p>}
        {profile.instagram && <p className="flex items-center gap-2"><AtSign className="size-3.5" />{profile.instagram}</p>}
      </div>
    </Card>
  )
}
