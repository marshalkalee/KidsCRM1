import { useEffect, useRef, useState } from 'react'
import { Camera, Loader2, Upload } from 'lucide-react'
import api from '../api/axios'
import { Button, Checkbox, DateInput, Field, Input, Modal, Select, Textarea, apiErrorMessage, cn, useToast } from '../ui'
import { t } from '../i18n'

const EMPTY = {
  full_name: '',
  birth_date: '',
  gender: '',
  status: 'active',
  directions: [],
  medical_notes: '',
  consent_given: false,
  leave_reason: '',
  photo_url: '',
}

function initialForm(child) {
  if (!child) return EMPTY
  return Object.fromEntries(Object.keys(EMPTY).map(key => [key, child[key] ?? EMPTY[key]]))
}

/**
 * Создание (child не передан) и редактирование ребёнка. Проверки — на
 * сервере (ChildSerializer: дата не в будущем, причина ухода для «Ушёл»,
 * допустимые переходы статуса); ошибки показываются у своих полей.
 */
export default function ChildModal({ child, onClose, onSaved }) {
  const isEdit = Boolean(child)
  const toast = useToast()
  const [form, setForm] = useState(() => initialForm(child))
  const [directions, setDirections] = useState([])
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('directions/').then(r => setDirections(r.data.results || r.data)).catch(() => {})
  }, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const toggleDirection = id => set(
    'directions',
    form.directions.includes(id) ? form.directions.filter(x => x !== id) : [...form.directions, id],
  )

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const response = isEdit
        ? await api.patch(`clients/children/${child.id}/`, form)
        : await api.post('clients/children/', form)
      toast.success(isEdit ? t('Изменения сохранены') : t('Ребёнок добавлен'))
      onSaved(response.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={isEdit ? t('Редактировать ребёнка') : t('Новый ребёнок')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="child-form" loading={saving}>
            {isEdit ? t('Сохранить') : t('Создать ребёнка')}
          </Button>
        </>
      }
    >
      <form id="child-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <PhotoPicker value={form.photo_url} onChange={url => set('photo_url', url)} error={errors.photo_url} />
        <Field label={t('ФИО')} required error={errors.full_name}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} value={form.full_name} onChange={e => set('full_name', e.target.value)} placeholder={t('Введите ФИО')} required autoFocus />
          )}
        </Field>
        <Field label={t('Дата рождения')} required error={errors.birth_date}>
          {({ id, invalid }) => (
            <DateInput id={id} invalid={invalid} value={form.birth_date} onChange={v => set('birth_date', v)} required />
          )}
        </Field>
        <Field label={t('Пол')} required error={errors.gender}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.gender} onChange={e => set('gender', e.target.value)} required>
              <option value="">{t('Выберите')}</option>
              <option value="female">{t('Девочка')}</option>
              <option value="male">{t('Мальчик')}</option>
            </Select>
          )}
        </Field>
        <Field label={t('Статус')} error={errors.status}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.status} onChange={e => set('status', e.target.value)}>
              <option value="active">{t('Активен')}</option>
              <option value="paused">{t('Приостановлен')}</option>
              <option value="left">{t('Ушёл')}</option>
            </Select>
          )}
        </Field>
        {form.status === 'left' ? (
          <Field label={t('Причина ухода')} required error={errors.leave_reason} className="sm:col-span-2">
            {({ id, invalid }) => (
              <Input id={id} invalid={invalid} value={form.leave_reason} onChange={e => set('leave_reason', e.target.value)} required />
            )}
          </Field>
        ) : null}

        {directions.length > 0 && (
          <Field label={t('Направления')} error={errors.directions} className="sm:col-span-2">
            <div className="flex flex-wrap gap-2">
              {directions.map(direction => {
                const active = form.directions.includes(direction.id)
                return (
                  <button
                    key={direction.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => toggleDirection(direction.id)}
                    className={cn(
                      'font-btn rounded-[20px] border px-3.5 py-1.5 text-xs font-medium transition-colors',
                      active ? 'border-brand-400 bg-brand-50 text-brand-600' : 'border-[#e5e7eb] bg-[#f8f9ff] text-ink-muted hover:text-ink',
                    )}
                  >
                    {direction.name}
                  </button>
                )
              })}
            </div>
          </Field>
        )}

        <Field label={t('Медицинские заметки')} error={errors.medical_notes} className="sm:col-span-2">
          {({ id }) => <Textarea id={id} value={form.medical_notes} onChange={e => set('medical_notes', e.target.value)} placeholder={t('Аллергии, особенности...')} />}
        </Field>
        <Checkbox
          className="sm:col-span-2"
          label={t('Согласие на обработку персональных данных получено')}
          checked={form.consent_given}
          onChange={e => set('consent_given', e.target.checked)}
        />
        {errors.non_field_errors && <p className="text-sm text-danger-600 sm:col-span-2">{errors.non_field_errors[0]}</p>}
      </form>
    </Modal>
  )
}

/**
 * Фото как в форме первого React: кружок и «Загрузить фото». Файл
 * отправляется сразу при выборе (clients/children/photo/), в форму
 * попадает ссылка — сохраняется вместе с ребёнком.
 */
function PhotoPicker({ value, onChange, error }) {
  const toast = useToast()
  const inputRef = useRef(null)
  const [uploading, setUploading] = useState(false)

  async function upload(file) {
    if (!file) return
    setUploading(true)
    try {
      const body = new FormData()
      body.append('file', file)
      const { data } = await api.post('clients/children/photo/', body)
      onChange(data.url)
    } catch (err) {
      toast.error(err.response?.data?.file?.[0] || apiErrorMessage(err))
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="flex items-center gap-4 sm:col-span-2">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        aria-label={value ? t('Заменить фото') : t('Загрузить фото')}
        className={cn(
          'flex size-[72px] shrink-0 items-center justify-center overflow-hidden rounded-full',
          value ? 'ring-2 ring-brand-100' : 'border-2 border-dashed border-[#e5e7eb] bg-[#f8f9ff] text-ink-subtle hover:border-brand-300 hover:text-brand-500',
        )}
      >
        {uploading ? <Loader2 className="size-6 animate-spin text-brand-500" />
          : value ? <img src={value} alt="" className="size-full object-cover" />
            : <Camera className="size-6" />}
      </button>
      <div className="flex flex-col items-start gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" icon={Upload} onClick={() => inputRef.current?.click()} disabled={uploading}>
            {value ? t('Заменить фото') : t('Загрузить фото')}
          </Button>
          {value && !uploading && <Button size="sm" variant="ghost" onClick={() => onChange('')}>{t('Убрать')}</Button>}
        </div>
        <p className="font-btn text-[11px] text-ink-subtle">{t('JPG, PNG до 5 МБ')}</p>
        {error && <p className="font-btn text-xs text-danger-600">{[].concat(error)[0]}</p>}
      </div>
      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={e => upload(e.target.files[0])} />
    </div>
  )
}
