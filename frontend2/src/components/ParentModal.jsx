import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import api from '../api/axios'
import { findParentsByPhones } from './parents/duplicates'
import { Button, Field, Input, Modal, Select, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'
import { personNameInput, personNameInputProps, phoneDigits, phoneInputProps } from '../utils/formValidation'

const PHONE_TYPES = { get mobile() { return t('Мобильный') }, get work() { return t('Рабочий') }, get home() { return t('Домашний') } }

/**
 * Создание/редактирование родителя. Телефоны уходят списком целиком — сервер
 * заменяет их (ParentContactSerializer.update), номер нормализует в +7….
 */
export default function ParentModal({ parent, onClose, onSaved }) {
  const isEdit = Boolean(parent)
  const toast = useToast()
  const [form, setForm] = useState({
    full_name: parent?.full_name || '',
    whatsapp: phoneDigits(parent?.whatsapp),
    email: parent?.email || '',
    phones: parent?.phones?.length ? parent.phones.map(({ number, phone_type }) => ({ number: phoneDigits(number), phone_type })) : [{ number: '', phone_type: 'mobile' }],
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  // Другие родители с теми же номерами: показаны — следующее «Сохранить» сохраняет.
  const [duplicates, setDuplicates] = useState(null)

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const setPhones = phones => { set('phones', phones); setDuplicates(null) }
  const setPhone = (index, key, value) => setPhones(form.phones.map((p, i) => (i === index ? { ...p, [key]: value } : p)))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    // Пустые строки не отправляем, но помним их места: ошибки сервера
    // приходят по индексам отправленного списка.
    const filled = form.phones.map((phone, index) => ({ phone, index })).filter(({ phone }) => phone.number.trim())
    const payload = { ...form, phones: filled.map(({ phone }) => phone) }
    try {
      if (!duplicates) {
        const before = new Set((parent?.phones || []).map(p => phoneDigits(p.number)))
        const added = filled.map(({ phone }) => phone.number).filter(number => !before.has(number))
        const found = added.length ? await findParentsByPhones(added, parent?.id) : []
        if (found.length) {
          setDuplicates(found)
          return
        }
      }
      const response = isEdit
        ? await api.patch(`clients/parents/${parent.id}/`, payload)
        : await api.post('clients/parents/', payload)
      toast.success(isEdit ? t('Изменения сохранены') : t('Родитель добавлен'))
      onSaved(response.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) {
        if (Array.isArray(data.phones) && typeof data.phones[0] !== 'string') {
          const phones = []
          data.phones.forEach((error, k) => { phones[filled[k].index] = error })
          setErrors({ ...data, phones })
        } else {
          setErrors(data)
        }
      } else {
        toast.error(apiErrorMessage(err))
      }
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
          <Button variant="primary" type="submit" form="parent-form" loading={saving}>
            {duplicates ? t('Сохранить всё равно') : isEdit ? t('Сохранить') : t('Добавить')}
          </Button>
        </>
      }
    >
      <form id="parent-form" onSubmit={submit} className="flex flex-col gap-4">
        <Field label={t('ФИО')} required error={errors.full_name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.full_name} onChange={e => set('full_name', personNameInput(e.target.value))} required autoFocus {...personNameInputProps} />}
        </Field>

        <Field label={t('Телефоны')} required error={phonesError}>
          <div className="flex flex-col gap-2">
            {form.phones.map((phone, index) => (
              <div key={index}>
                <div className="flex gap-2">
                  <Input
                    aria-label={t('Телефон {n}', { n: index + 1 })}
                    invalid={Boolean(phoneError(index))}
                    placeholder="77000000000"
                    value={phone.number}
                    onChange={e => setPhone(index, 'number', phoneDigits(e.target.value))}
                    required={index === 0}
                    {...phoneInputProps}
                  />
                  <Select aria-label={t('Тип')} className="w-36" value={phone.phone_type} onChange={e => setPhone(index, 'phone_type', e.target.value)}>
                    {Object.entries(PHONE_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </Select>
                  {form.phones.length > 1 && (
                    <Button variant="ghost" size="icon" aria-label={t('Убрать телефон')} onClick={() => setPhones(form.phones.filter((_, i) => i !== index))}>
                      <X className="size-4" />
                    </Button>
                  )}
                </div>
                {phoneError(index) && <p className="mt-1 text-xs text-danger-600">{phoneError(index)}</p>}
              </div>
            ))}
            <Button variant="ghost" size="sm" icon={Plus} className="self-start" onClick={() => setPhones([...form.phones, { number: '', phone_type: 'mobile' }])}>
              {t('Ещё телефон')}
            </Button>
          </div>
        </Field>
        {duplicates && <DuplicateParents parents={duplicates} />}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="WhatsApp" hint={t('Если отличается от телефона')} error={errors.whatsapp}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.whatsapp} onChange={e => set('whatsapp', phoneDigits(e.target.value))} placeholder="77000000000" {...phoneInputProps} />}
          </Field>
          <Field label="Email" error={errors.email}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="email" value={form.email} onChange={e => set('email', e.target.value)} />}
          </Field>
        </div>
      </form>
    </Modal>
  )
}

function DuplicateParents({ parents }) {
  return (
    <div role="alert" className="rounded-md bg-warning-50 px-3 py-2.5 text-[13px] text-warning-600">
      <p className="font-semibold">{t('Этот номер уже есть у другого родителя')}</p>
      <ul className="mt-1 flex flex-col gap-0.5">
        {parents.map(p => (
          <li key={p.id}>
            <Link to={`/parents/${p.id}`} target="_blank" className="underline hover:opacity-80">{p.full_name}</Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
