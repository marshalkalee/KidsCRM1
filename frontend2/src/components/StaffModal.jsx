import { useState } from 'react'
import api from '../api/axios'
import { Button, Field, Input, Modal, MultiSelect, Select, apiErrorMessage, useToast } from '../ui'
import { useSession } from '../session/SessionContext'
import { t } from '../i18n'
import { personNameInput, personNameInputProps, phoneDigits, phoneInputProps } from '../utils/formValidation'

const ROLES = [
  ['manager', 'Управляющий'],
  ['admin', 'Администратор'],
  ['teacher', 'Преподаватель'],
  ['accountant', 'Бухгалтер'],
]

export default function StaffModal({ staff, branches, onClose, onSaved }) {
  const { user } = useSession()
  const toast = useToast()
  const isEdit = Boolean(staff)
  const [form, setForm] = useState({
    full_name: staff?.full_name || '',
    phone: staff?.phone || '+7',
    role: staff?.role || 'teacher',
    branches: (staff?.branches || []).map(String),
    password: '',
    is_active: staff?.is_active ?? true,
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))

  async function submit(event) {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    const payload = { ...form }
    if (isEdit && !payload.password) delete payload.password
    try {
      if (isEdit) await api.patch(`users/${staff.id}/`, payload)
      else await api.post('users/', payload)
      toast.success(isEdit ? t('Сотрудник сохранён') : t('Сотрудник добавлен'))
      onSaved()
    } catch (error) {
      const data = error.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const roles = user?.role === 'owner' ? [['owner', 'Владелец'], ...ROLES] : ROLES
  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? t('Редактировать сотрудника') : t('Новый сотрудник')}
      footer={<><Button onClick={onClose}>{t('Отмена')}</Button><Button variant="primary" type="submit" form="staff-form" loading={saving}>{t('Сохранить')}</Button></>}
    >
      <form id="staff-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label={t('ФИО')} error={errors.full_name} required className="sm:col-span-2">
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.full_name} onChange={event => set('full_name', personNameInput(event.target.value))} required autoFocus {...personNameInputProps} />}
        </Field>
        <Field label={t('Телефон')} error={errors.phone} required>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.phone} onChange={event => set('phone', phoneDigits(event.target.value))} required {...phoneInputProps} />}
        </Field>
        <Field label={t('Роль')} error={errors.role} required>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.role} onChange={event => set('role', event.target.value)} required>
              {roles.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            </Select>
          )}
        </Field>
        <Field label={t('Филиалы')} hint={t('Если ничего не выбрать, сотруднику будут доступны все филиалы.')} error={errors.branches} className="sm:col-span-2">
          {({ id, invalid }) => <MultiSelect id={id} invalid={invalid} value={form.branches} onChange={value => set('branches', value)} options={branches.map(branch => ({ value: String(branch.id), label: branch.name }))} placeholder={t('Все филиалы')} />}
        </Field>
        <Field label={t('Пароль для входа')} hint={isEdit ? t('Оставьте пустым, чтобы не менять пароль') : t('Не менее 8 символов')} error={errors.password} className="sm:col-span-2" required={!isEdit}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} type="password" minLength={8} value={form.password} onChange={event => set('password', event.target.value)} required={!isEdit} autoComplete="new-password" />}
        </Field>
        {isEdit && (
          <Field label={t('Статус')} error={errors.is_active} className="sm:col-span-2">
            {({ id }) => (
              <Select id={id} value={form.is_active ? 'active' : 'disabled'} onChange={event => set('is_active', event.target.value === 'active')}>
                <option value="active">{t('Активен')}</option>
                <option value="disabled">{t('Отключён')}</option>
              </Select>
            )}
          </Field>
        )}
      </form>
    </Modal>
  )
}
