import { useEffect, useState } from 'react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import { Button, Field, Input, Modal, Select, apiErrorMessage, useToast } from '../../ui'
import { t } from '../../i18n'
import { personNameInput, personNameInputProps, phoneDigits, phoneInputProps } from '../../utils/formValidation'

/** Редактирование заявки из карточки (TRU-96): контакт, ребёнок, направление, источник, филиал. */
export default function LeadModal({ lead, onClose, onSaved }) {
  const toast = useToast()
  const { branches } = useSession()
  const [form, setForm] = useState({
    parent_name: lead.parent_name,
    phone: phoneDigits(lead.phone),
    child_name: lead.child_name,
    child_age: lead.child_age ?? '',
    direction: lead.direction || '',
    source: lead.source || '',
    campaign: lead.campaign || '',
    branch: lead.branch || '',
  })
  const [sources, setSources] = useState([])
  const [campaigns, setCampaigns] = useState([])
  const [directions, setDirections] = useState([])
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  useEffect(() => {
    api.get('leads/sources/').then(res => setSources(res.data)).catch(() => {})
    api.get('leads/campaigns/').then(res => setCampaigns(res.data)).catch(() => {})
    api.get('directions/').then(res => setDirections(res.data.results || res.data)).catch(() => {})
  }, [])

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const res = await api.patch(`leads/${lead.id}/`, {
        ...form,
        child_age: form.child_age === '' ? null : Number(form.child_age),
        direction: form.direction || null,
        source: form.source || null,
        campaign: form.campaign || null,
        branch: form.branch || null,
      })
      toast.success(t('Заявка сохранена'))
      onSaved(res.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const error = key => (errors[key] ? t(errors[key][0]) : null)
  // Архивные значения не выбрать заново, но уже стоящее у заявки — видно.
  const sourceOptions = sources.filter(s => s.is_active || s.id === lead.source)
  // Публикации выбранного источника (TRU-165); архивная, уже стоящая у заявки, — видна.
  const campaignOptions = campaigns.filter(c => c.source === form.source && (c.is_active || c.id === lead.campaign))
  const directionOptions = directions.filter(d => d.is_active || d.id === lead.direction)
  const branchOptions = branches.filter(b => b.is_active !== false || b.id === lead.branch)

  return (
    <Modal
      open
      onClose={onClose}
      title={t('Редактировать заявку')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="lead-form" loading={saving}>{t('Сохранить')}</Button>
        </>
      }
    >
      <form id="lead-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        <Field label={t('Имя родителя')} required error={error('parent_name')}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.parent_name} onChange={e => set('parent_name', personNameInput(e.target.value))} required {...personNameInputProps} />}
        </Field>
        <Field label={t('Телефон')} required error={error('phone')}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.phone} onChange={e => set('phone', phoneDigits(e.target.value))} placeholder="77000000000" required {...phoneInputProps} />}
        </Field>
        <Field label={t('Имя ребёнка')} error={error('child_name')}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.child_name} onChange={e => set('child_name', personNameInput(e.target.value))} {...personNameInputProps} />}
        </Field>
        <Field label={t('Возраст')} error={error('child_age')}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" inputMode="numeric" min={1} max={25} value={form.child_age} onChange={e => set('child_age', e.target.value)} />}
        </Field>
        <Field label={t('Направление')} error={error('direction')}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.direction} onChange={e => set('direction', e.target.value)}>
              <option value="">{t('Не выбрано')}</option>
              {directionOptions.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          )}
        </Field>
        <Field label={t('Источник')} error={error('source')}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.source} onChange={e => setForm(f => ({ ...f, source: e.target.value, campaign: '' }))}>
              <option value="">{t('Не выбран')}</option>
              {sourceOptions.map(s => <option key={s.id} value={s.id}>{t(s.name)}</option>)}
            </Select>
          )}
        </Field>
        {campaignOptions.length > 0 && (
          <Field label={t('Публикация')} error={error('campaign')}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.campaign} onChange={e => set('campaign', e.target.value)}>
                <option value="">{t('Не знаем')}</option>
                {campaignOptions.map(c => <option key={c.id} value={c.id}>{c.name} · {c.code}</option>)}
              </Select>
            )}
          </Field>
        )}
        {branchOptions.length > 1 && (
          <Field label={t('Филиал')} error={error('branch')}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.branch} onChange={e => set('branch', e.target.value)}>
                <option value="">{t('Не выбран')}</option>
                {branchOptions.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
          </Field>
        )}
      </form>
    </Modal>
  )
}
