import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import api from '../api/axios'
import { Button, Field, Input, Modal, Select, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'

const PHONE_TYPES = { mobile: t('Мобильный'), work: t('Рабочий'), home: t('Домашний') }

/**
 * Создание/редактирование родителя. Телефоны уходят списком целиком — сервер
 * заменяет их (ParentContactSerializer.update), номер нормализует в +7….
 */
export default function ParentModal({ parent, onClose, onSaved }) {
  const isEdit = Boolean(parent)
  const toast = useToast()
  const [form, setForm] = useState({
    full_name: parent?.full_name || '',
    whatsapp: parent?.whatsapp || '',
    email: parent?.email || '',
    phones: parent?.phones?.length ? parent.phones.map(({ number, phone_type }) => ({ number, phone_type })) : [{ number: '', phone_type: 'mobile' }],
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const setPhone = (index, key, value) => set('phones', form.phones.map((p, i) => (i === index ? { ...p, [key]: value } : p)))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    const payload = { ...form, phones: form.phones.filter(p => p.number.trim()) }
    try {
      const response = isEdit
        ? await api.patch(`clients/parents/${parent.id}/`, payload)
        : await api.post('clients/parents/', payload)
      toast.success(isEdit ? t('Изменения сохранены') : t('Родитель добавлен'))
      onSaved(response.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  // DRF: phones — либо ['У родителя должен быть…'], либо [{number: [...]}, {}].
  const phonesError = Array.isArray(errors.phones) && typeof errors.phones[0] === 'string' ? errors.phones[0] : null
  const phoneError = index => (Array.isArray(errors.phones) ? errors.phones[index]?.number?.[0] : null)

  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? t('Редактировать родителя') : t('Новый родитель')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="parent-form" loading={saving}>{isEdit ? t('Сохранить') : t('Добавить')}</Button>
        </>
      }
    >
      <form id="parent-form" onSubmit={submit} className="flex flex-col gap-4">
        <Field label={t('ФИО')} required error={errors.full_name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.full_name} onChange={e => set('full_name', e.target.value)} required autoFocus />}
        </Field>

        <Field label={t('Телефоны')} required error={phonesError}>
          <div className="flex flex-col gap-2">
            {form.phones.map((phone, index) => (
              <div key={index}>
                <div className="flex gap-2">
                  <Input
                    aria-label={t('Телефон {n}', { n: index + 1 })}
                    invalid={Boolean(phoneError(index))}
                    type="tel"
                    inputMode="tel"
                    placeholder="+7 700 000 00 00"
                    value={phone.number}
                    onChange={e => setPhone(index, 'number', e.target.value)}
                  />
                  <Select aria-label={t('Тип')} className="w-36" value={phone.phone_type} onChange={e => setPhone(index, 'phone_type', e.target.value)}>
                    {Object.entries(PHONE_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </Select>
                  {form.phones.length > 1 && (
                    <Button variant="ghost" size="icon" aria-label={t('Убрать телефон')} onClick={() => set('phones', form.phones.filter((_, i) => i !== index))}>
                      <X className="size-4" />
                    </Button>
                  )}
                </div>
                {phoneError(index) && <p className="mt-1 text-xs text-danger-600">{phoneError(index)}</p>}
              </div>
            ))}
            <Button variant="ghost" size="sm" icon={Plus} className="self-start" onClick={() => set('phones', [...form.phones, { number: '', phone_type: 'mobile' }])}>
              {t('Ещё телефон')}
            </Button>
          </div>
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="WhatsApp" hint={t('Если отличается от телефона')} error={errors.whatsapp}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="tel" inputMode="tel" value={form.whatsapp} onChange={e => set('whatsapp', e.target.value)} />}
          </Field>
          <Field label="Email" error={errors.email}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="email" value={form.email} onChange={e => set('email', e.target.value)} />}
          </Field>
        </div>
      </form>
    </Modal>
  )
}
