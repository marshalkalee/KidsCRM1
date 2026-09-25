import { useEffect, useState } from 'react'
import api from '../api/axios'
import { Button, Card, CardHeader, ErrorState, Field, Input, Select, Skeleton, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'

// Пороги автостатусов (backend: tenants/org_settings.py) — по ним экраны
// продлений, задолженностей и групп решают, кого подсветить.
const THRESHOLDS = [
  { key: 'subscription_ending_lessons_threshold', get label() { return t('Мало занятий на абонементе') }, get hint() { return t('Попадает в «Продления»') }, get suffix() { return t('занятий и меньше') }, max: 100 },
  { key: 'subscription_ending_days_threshold', get label() { return t('Абонемент скоро закончится') }, get hint() { return t('Попадает в «Продления»') }, get suffix() { return t('дней и меньше') }, max: 365 },
  { key: 'debt_overdue_days_threshold', get label() { return t('Долг просрочен') }, get hint() { return t('Неоплаченный абонемент старше') }, get suffix() { return t('дней') }, max: 365 },
  { key: 'group_underfilled_percent_threshold', get label() { return t('Группа недозаполнена') }, get hint() { return t('Заполненность группы') }, get suffix() { return t('% и меньше') }, max: 100 },
]

/**
 * Форма настроек организации — одна на экран «Организация» и шаг мастера
 * онбординга (TRU-86). Сохранение тем же путём, что у старого веба:
 * organization/settings/ → OrganizationSettingsForm.
 * secondaryAction — дополнительная кнопка слева от «Сохранить» (в мастере — «Пропустить»).
 */
export default function OrganizationForm({ onSaved, submitLabel = t('Сохранить'), secondaryAction }) {
  const toast = useToast()
  const [form, setForm] = useState(null)
  const [timezones, setTimezones] = useState([])
  const [errors, setErrors] = useState({})
  const [status, setStatus] = useState('loading')
  const [saving, setSaving] = useState(false)

  const load = () => {
    api.get('organization/settings/')
      .then(({ data: { timezones: list, ...values } }) => { setForm(values); setTimezones(list); setStatus('ready') })
      .catch(() => setStatus('error'))
  }
  useEffect(load, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const { data: { timezones: _list, ...values } } = await api.put('organization/settings/', form)
      setForm(values)
      toast.success(t('Настройки сохранены'))
      onSaved?.(values)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {status === 'loading' && <Skeleton className="h-96 max-w-3xl" />}
      {status === 'error' && <Card><ErrorState onRetry={() => { setStatus('loading'); load() }} /></Card>}
      {status === 'ready' && (
        <form onSubmit={submit} className="max-w-3xl space-y-4">
          <Card>
            <CardHeader title={t('Основное')} />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t('Название')} required error={errors.name}>
                {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name || ''} onChange={e => set('name', e.target.value)} required />}
              </Field>
              <Field label={t('Часовой пояс')} hint={t('От него зависят время занятий и «сегодня» в отчётах')} error={errors.timezone}>
                {({ id, invalid }) => (
                  <Select id={id} invalid={invalid} value={form.timezone || ''} onChange={e => set('timezone', e.target.value)}>
                    {timezones.map(tz => <option key={tz} value={tz}>{tz.replace('_', ' ')}</option>)}
                  </Select>
                )}
              </Field>
            </div>
          </Card>

          <Card>
            <CardHeader title={t('Пороги автостатусов')} description={t('Когда система сама помечает ребёнка или группу.')} />
            <div className="divide-y divide-line">
              {THRESHOLDS.map(th => (
                <div key={th.key} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
                  <label htmlFor={th.key} className="min-w-0">
                    <span className="block text-sm font-semibold text-ink">{th.label}</span>
                    <span className="block text-[13px] text-ink-muted">{th.hint}</span>
                  </label>
                  <div className="shrink-0">
                    <div className="flex items-center gap-2 sm:w-64">
                      <div className="w-20 shrink-0">
                        <Input
                          id={th.key}
                          type="number"
                          min={0}
                          max={th.max}
                          className="text-right"
                          invalid={Boolean(errors[th.key])}
                          value={form[th.key] ?? ''}
                          onChange={e => set(th.key, e.target.value === '' ? '' : Number(e.target.value))}
                        />
                      </div>
                      <span className="whitespace-nowrap text-sm text-ink-muted">{th.suffix}</span>
                    </div>
                    {errors[th.key] && <p className="mt-1 text-xs text-danger-600">{errors[th.key][0]}</p>}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <div className="flex flex-wrap justify-end gap-2">
            {secondaryAction}
            <Button variant="primary" type="submit" loading={saving}>{submitLabel}</Button>
          </div>
        </form>
      )}
    </>
  )
}
