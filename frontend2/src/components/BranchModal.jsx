import { useEffect, useState } from 'react'
import api from '../api/axios'
import { Button, Checkbox, Field, Input, Modal, Select, Textarea, apiErrorMessage, useToast } from '../ui'
import { WEEKDAYS, initialHours } from './workingHours'
import { t } from '../i18n'
import { entityNameInputProps, phoneDigits, phoneInputProps } from '../utils/formValidation'

export default function BranchModal({ branch, onClose, onSaved }) {
  const isEdit = Boolean(branch)
  const toast = useToast()
  const [form, setForm] = useState({
    name: branch?.name || '',
    address: branch?.address || '',
    city: branch?.city || '',
    district: branch?.district || '',
    phone: phoneDigits(branch?.phone),
  })
  // Точка на карте (TRU-178): ставится по адресу сама; поправить — вручную.
  const [editPoint, setEditPoint] = useState(false)
  const [point, setPoint] = useState({ latitude: branch?.latitude ?? '', longitude: branch?.longitude ?? '' })
  const [cities, setCities] = useState([])
  useEffect(() => { api.get('branches/cities/').then(res => setCities(res.data)).catch(() => {}) }, [])
  const [hours, setHours] = useState(() => initialHours(branch?.working_hours))
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const setDay = (code, patch) => setHours(h => ({ ...h, [code]: { ...h[code], ...patch } }))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    const working_hours = Object.fromEntries(Object.entries(hours).map(([code, day]) => [
      code, day.closed ? { closed: true } : { closed: false, open: day.open, close: day.close },
    ]))
    try {
      const payload = { ...form, working_hours }
      if (editPoint && point.latitude !== '' && point.longitude !== '') {
        payload.latitude = point.latitude
        payload.longitude = point.longitude
      }
      const response = isEdit ? await api.patch(`branches/${branch.id}/`, payload) : await api.post('branches/', payload)
      toast.success(isEdit ? t('Филиал сохранён') : t('Филиал добавлен'))
      onSaved(response.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const hourErrors = errors.working_hours && typeof errors.working_hours === 'object' ? errors.working_hours : {}

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={isEdit ? t('Редактировать филиал') : t('Новый филиал')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="branch-form" loading={saving}>{isEdit ? t('Сохранить') : t('Создать филиал')}</Button>
        </>
      }
    >
      <form id="branch-form" onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t('Название')} required error={errors.name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder={t('Центральный филиал')} required autoFocus {...entityNameInputProps} />}
        </Field>
        <div className="grid gap-3.5 sm:grid-cols-2">
          <Field label={t('Город')} required={!isEdit} error={errors.city}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.city} onChange={e => setForm(f => ({ ...f, city: e.target.value }))} required={!isEdit}>
                <option value="">{t('Выберите город')}</option>
                {cities.map(city => <option key={city} value={city}>{city}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('Район')} error={errors.district}>
            {({ id }) => <Input id={id} value={form.district} onChange={e => setForm(f => ({ ...f, district: e.target.value }))} maxLength={100} placeholder={t('Например, Бостандыкский')} />}
          </Field>
        </div>
        <Field label={t('Адрес')} error={errors.address} hint={t('Улица и дом — по ним сама ставится точка на карте.')}>
          {({ id }) => <Textarea id={id} rows={2} value={form.address} onChange={e => setForm(f => ({ ...f, address: e.target.value }))} maxLength={500} />}
        </Field>
        {isEdit && (
          <div className="rounded-lg bg-surface-muted px-3 py-2.5 text-[13px]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-ink-muted">
                {branch.latitude != null
                  ? <>{t('Точка на карте')}: <span className="text-ink">{Number(branch.latitude).toFixed(5)}, {Number(branch.longitude).toFixed(5)}</span> · {branch.coordinates_source === 'manual' ? t('поставлена вручную') : t('по адресу')}</>
                  : t('Точки на карте пока нет — появится по адресу после сохранения.')}
              </span>
              <span className="flex gap-3">
                {branch.latitude != null && (
                  <a className="font-semibold text-brand-600 hover:underline" target="_blank" rel="noopener noreferrer" href={`https://www.openstreetmap.org/?mlat=${branch.latitude}&mlon=${branch.longitude}#map=17/${branch.latitude}/${branch.longitude}`}>{t('Проверить на карте')}</a>
                )}
                <button type="button" className="font-semibold text-brand-600 hover:underline" onClick={() => setEditPoint(v => !v)}>{t('Поправить точку')}</button>
              </span>
            </div>
            {editPoint && (
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <Field label={t('Широта')} error={errors.latitude}>
                  {({ id, invalid }) => <Input id={id} invalid={invalid} inputMode="decimal" value={point.latitude} onChange={e => setPoint(p => ({ ...p, latitude: e.target.value.replace(',', '.') }))} placeholder="43.238949" />}
                </Field>
                <Field label={t('Долгота')}>
                  {({ id }) => <Input id={id} inputMode="decimal" value={point.longitude} onChange={e => setPoint(p => ({ ...p, longitude: e.target.value.replace(',', '.') }))} placeholder="76.889709" />}
                </Field>
                <p className="text-[12px] text-ink-muted sm:col-span-2">{t('Откройте место на карте, скопируйте координаты. Поставленную вручную точку система больше не пересчитывает.')}</p>
              </div>
            )}
          </div>
        )}
        <Field label={t('Телефон')} error={errors.phone}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.phone} onChange={e => setForm(f => ({ ...f, phone: phoneDigits(e.target.value) }))} placeholder="77000000000" {...phoneInputProps} />}
        </Field>
        <div>
          <p className="font-btn mb-2.5 text-sm font-bold text-ink">{t('Часы работы')}</p>
          <div className="flex flex-col gap-2">
            {WEEKDAYS.map(([code, , full]) => {
              const day = hours[code]
              return (
                <div key={code}>
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="font-btn w-[100px] shrink-0 text-xs text-[#374151]">{t(full)}</span>
                    <Checkbox className="w-[90px] shrink-0 text-xs" label={t('Выходной')} checked={day.closed} onChange={e => setDay(code, { closed: e.target.checked })} />
                    {!day.closed && (
                      <div className="flex items-center gap-1.5">
                        <Input type="time" aria-label={t('{day}, открытие', { day: t(full) })} className="h-8 w-[100px] px-2 text-xs" value={day.open} onChange={e => setDay(code, { open: e.target.value })} required />
                        <span className="text-ink-subtle">—</span>
                        <Input type="time" aria-label={t('{day}, закрытие', { day: t(full) })} className="h-8 w-[100px] px-2 text-xs" value={day.close} onChange={e => setDay(code, { close: e.target.value })} required />
                      </div>
                    )}
                  </div>
                  {hourErrors[code] && <p className="font-btn mt-1 text-[11px] text-danger-600">{[].concat(hourErrors[code])[0]}</p>}
                </div>
              )
            })}
          </div>
        </div>
      </form>
    </Modal>
  )
}
