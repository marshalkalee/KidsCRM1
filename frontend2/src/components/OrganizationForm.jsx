import { useEffect, useState } from 'react'
import api from '../api/axios'
import { Button, Card, CardHeader, ErrorState, Field, Input, Select, Skeleton, apiErrorMessage, useToast } from '../ui'

// Пороги автостатусов (backend: tenants/org_settings.py) — по ним экраны
// продлений, задолженностей и групп решают, кого подсветить.
const THRESHOLDS = [
  { key: 'subscription_ending_lessons_threshold', label: 'Мало занятий на абонементе', hint: 'Попадает в «Продления»', suffix: 'занятий и меньше', max: 100 },
  { key: 'subscription_ending_days_threshold', label: 'Абонемент скоро закончится', hint: 'Попадает в «Продления»', suffix: 'дней и меньше', max: 365 },
  { key: 'debt_overdue_days_threshold', label: 'Долг просрочен', hint: 'Неоплаченный абонемент старше', suffix: 'дней', max: 365 },
  { key: 'group_underfilled_percent_threshold', label: 'Группа недозаполнена', hint: 'Заполненность группы', suffix: '% и меньше', max: 100 },
]

/**
 * Форма настроек организации — одна на экран «Организация» и шаг мастера
 * онбординга (TRU-86). Сохранение тем же путём, что у старого веба:
 * organization/settings/ → OrganizationSettingsForm.
 * secondaryAction — дополнительная кнопка слева от «Сохранить» (в мастере — «Пропустить»).
 */
export default function OrganizationForm({ onSaved, submitLabel = 'Сохранить', secondaryAction }) {
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
      toast.success('Настройки сохранены')
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
            <CardHeader title="Основное" />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Название" required error={errors.name}>
                {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name || ''} onChange={e => set('name', e.target.value)} required />}
              </Field>
              <Field label="Часовой пояс" hint="От него зависят время занятий и «сегодня» в отчётах" error={errors.timezone}>
                {({ id, invalid }) => (
                  <Select id={id} invalid={invalid} value={form.timezone || ''} onChange={e => set('timezone', e.target.value)}>
                    {timezones.map(tz => <option key={tz} value={tz}>{tz.replace('_', ' ')}</option>)}
                  </Select>
                )}
              </Field>
            </div>
          </Card>

          <Card>
            <CardHeader title="Пороги автостатусов" description="Когда система сама помечает ребёнка или группу." />
            <div className="divide-y divide-line">
              {THRESHOLDS.map(t => (
                <div key={t.key} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
                  <label htmlFor={t.key} className="min-w-0">
                    <span className="block text-sm font-semibold text-ink">{t.label}</span>
                    <span className="block text-[13px] text-ink-muted">{t.hint}</span>
                  </label>
                  <div className="shrink-0">
                    <div className="flex items-center gap-2 sm:w-64">
                      <div className="w-20 shrink-0">
                        <Input
                          id={t.key}
                          type="number"
                          min={0}
                          max={t.max}
                          className="text-right"
                          invalid={Boolean(errors[t.key])}
                          value={form[t.key] ?? ''}
                          onChange={e => set(t.key, e.target.value === '' ? '' : Number(e.target.value))}
                        />
                      </div>
                      <span className="whitespace-nowrap text-sm text-ink-muted">{t.suffix}</span>
                    </div>
                    {errors[t.key] && <p className="mt-1 text-xs text-danger-600">{errors[t.key][0]}</p>}
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
