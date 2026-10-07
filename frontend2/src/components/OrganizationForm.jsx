import { useEffect, useState } from 'react'
import { BellRing, Building2, CalendarX2, Gauge, Globe, Newspaper } from 'lucide-react'
import api from '../api/axios'
import { Button, Card, CardHeader, Checkbox, ErrorState, Field, Input, Select, Skeleton, apiErrorMessage, cn, useToast } from '../ui'
import { locale, t } from '../i18n'
import { useAI } from './ai/ai'
import { entityNameInputProps } from '../utils/formValidation'

// Пороги автостатусов (backend: tenants/org_settings.py) — по ним экраны
// продлений, задолженностей и групп решают, кого подсветить.
const THRESHOLDS = [
  { key: 'subscription_ending_lessons_threshold', get label() { return t('Мало занятий на абонементе') }, get hint() { return t('Попадает в «Продления»') }, get suffix() { return t('занятий и меньше') }, max: 100 },
  { key: 'subscription_ending_days_threshold', get label() { return t('Абонемент скоро закончится') }, get hint() { return t('Попадает в «Продления»') }, get suffix() { return t('дней и меньше') }, max: 365 },
  { key: 'debt_overdue_days_threshold', get label() { return t('Долг просрочен') }, get hint() { return t('Неоплаченный абонемент старше') }, get suffix() { return t('дней') }, max: 365 },
  { key: 'group_underfilled_percent_threshold', get label() { return t('Группа недозаполнена') }, get hint() { return t('Заполненность группы') }, get suffix() { return t('% и меньше') }, max: 100 },
  { key: 'risk_absence_change_pp_threshold', get label() { return t('Рост пропусков для риск-листа') }, get hint() { return t('Отклонение от личной нормы ребёнка') }, get suffix() { return t('п.п. и больше') }, min: 1, max: 100 },
  { key: 'risk_current_absences_min', get label() { return t('Минимум пропусков для риск-листа') }, get hint() { return t('За выбранный период') }, get suffix() { return t('пропуска и больше') }, min: 1, max: 100 },
  { key: 'renewal_grace_days', get label() { return t('Что считать продлением') }, get hint() { return t('Новый абонемент после окончания прошлого — не позже') }, get suffix() { return t('дней') }, max: 120 },
  { key: 'lead_stale_days_threshold', get label() { return t('Заявка без движения') }, get hint() { return t('Напомнить перезвонить через') }, get suffix() { return t('дней') }, max: 90 },
]

// Автоправила создания задач (TRU-108) — владелец может выключить любое.
const RULES = [
  { key: 'rule_lead_stale_enabled', get label() { return t('Напоминать перезвонить по зависшим заявкам') } },
  { key: 'rule_renewal_offer_enabled', get label() { return t('Предлагать продление заранее') } },
  { key: 'rule_debt_reminder_enabled', get label() { return t('Напоминать о просроченном долге') } },
  { key: 'rule_missing_subscription_enabled', get label() { return t('Напоминать оформить абонемент без него') } },
  { key: 'rule_trial_no_show_enabled', get label() { return t('Напоминать перезвонить после пропуска пробного') } },
]

/**
 * Форма настроек организации — одна на экран «Организация» и шаг мастера
 * онбординга (TRU-86). Сохранение тем же путём, что у старого веба:
 * organization/settings/ → OrganizationSettingsForm.
 * wide — экран «Организация»: карточки в две колонки на всю ширину и
 * панель «Сохранить» всегда внизу экрана; в мастере — одна колонка.
 * secondaryAction — дополнительная кнопка слева от «Сохранить» (в мастере — «Пропустить»).
 */
export default function OrganizationForm({ onSaved, submitLabel = t('Сохранить'), secondaryAction, wide = false }) {
  const toast = useToast()
  const ai = useAI()
  const [form, setForm] = useState(null)
  const [saved, setSaved] = useState(null)
  const [timezones, setTimezones] = useState([])
  const [errors, setErrors] = useState({})
  const [status, setStatus] = useState('loading')
  const [saving, setSaving] = useState(false)

  const load = () => {
    api.get('organization/settings/')
      .then(({ data: { timezones: list, ...values } }) => { setForm(values); setSaved(values); setTimezones(list); setStatus('ready') })
      .catch(() => setStatus('error'))
  }
  useEffect(load, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const dirty = form && saved && JSON.stringify(form) !== JSON.stringify(saved)

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const { data: { timezones: _list, ...values } } = await api.put('organization/settings/', form)
      setForm(values)
      setSaved(values)
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

  async function copyKey() {
    try {
      await navigator.clipboard.writeText(form.public_api_key)
      toast.success(t('Ключ скопирован'))
    } catch {
      toast.error(t('Не удалось скопировать — выделите и скопируйте вручную'))
    }
  }

  if (status === 'loading') return <Skeleton className={cn('h-96', !wide && 'max-w-3xl')} />
  if (status === 'error') return <Card><ErrorState onRetry={() => { setStatus('loading'); load() }} /></Card>

  const main = (
    <Section icon={Building2} title={t('Основное')} wide={wide}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('Название')} required error={errors.name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.name || ''} onChange={e => set('name', e.target.value)} required {...entityNameInputProps} />}
        </Field>
        <Field label={t('Часовой пояс')} hint={t('От него зависят время занятий и «сегодня» в отчётах')} error={errors.timezone}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.timezone || ''} onChange={e => set('timezone', e.target.value)}>
              {timezones.map(tz => <option key={tz} value={tz}>{tz.replace('_', ' ')}</option>)}
            </Select>
          )}
        </Field>
      </div>
    </Section>
  )

  const cancel = (
    <Section
      icon={CalendarX2}
      title={t('Отмена занятия родителем')}
      description={t('Родитель сможет предупредить о пропуске и позже срока, но система заранее покажет правило списания.')}
      wide={wide}
    >
      <div className="space-y-4">
        <Field
          label={t('Срок своевременного предупреждения')}
          hint={t('Не позднее чем за указанное число часов до начала занятия.')}
          error={errors.parent_cancel_notice_hours}
        >
          {({ id, invalid }) => (
            <div className="flex max-w-[12rem] items-center gap-2">
              <Input
                id={id}
                type="number"
                min={0}
                max={168}
                className="text-right"
                invalid={invalid}
                value={form.parent_cancel_notice_hours ?? 24}
                onChange={e => set('parent_cancel_notice_hours', e.target.value === '' ? '' : Number(e.target.value))}
              />
              <span className="text-sm text-ink-muted">{t('часов')}</span>
            </div>
          )}
        </Field>
        <div className="rounded-lg bg-surface-muted px-3 py-2.5">
          <Checkbox
            checked={Boolean(form.parent_cancel_charge_on_time)}
            onChange={e => set('parent_cancel_charge_on_time', e.target.checked)}
            label={<span className="text-ink">{t('Списывать занятие даже при своевременном предупреждении')}</span>}
          />
          <p className="mt-1.5 pl-7 text-[13px] text-ink-muted">
            {form.parent_cancel_charge_on_time
              ? t('При любом предупреждении занятие списывается по правилам центра.')
              : t('Своевременное предупреждение не списывает занятие; позднее — списывает.')}
          </p>
        </div>
      </div>
    </Section>
  )

  const site = (
    <Section icon={Globe} title={t('Приём заявок с сайта')} description={t('Для формы на сайте центра, которая отправляет заявки напрямую в CRM.')} wide={wide}>
      <div className="space-y-4">
        <Field label={t('Домен сайта')} hint={t('Форма сможет слать заявки только с этого адреса')} error={errors.website_domain}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} placeholder="https://trueballet.kz" value={form.website_domain || ''} onChange={e => set('website_domain', e.target.value)} />
          )}
        </Field>
        <div>
          <p className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Ключ для формы')}</p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md border border-line bg-surface-muted px-3 py-2 text-[13px] text-ink">{form.public_api_key}</code>
            <Button type="button" size="sm" variant="secondary" onClick={copyKey}>{t('Копировать')}</Button>
          </div>
        </div>
      </div>
    </Section>
  )

  const thresholds = (
    <Section icon={Gauge} title={t('Пороги автостатусов')} description={t('Когда система сама помечает ребёнка или группу.')} wide={wide}>
      <div className={cn('grid grid-cols-1 gap-3', wide && 'lg:grid-cols-2')}>
        {THRESHOLDS.map(th => (
          <div key={th.key} className="flex flex-col gap-2 rounded-lg border border-line px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <label htmlFor={th.key} className="min-w-0">
              <span className="block text-sm font-semibold text-ink">{th.label}</span>
              <span className="block text-[13px] text-ink-muted">{th.hint}</span>
            </label>
            <div className="shrink-0">
              <div className="flex items-center gap-2">
                <div className="w-20 shrink-0">
                  <Input
                    id={th.key}
                    type="number"
                    min={th.min ?? 0}
                    max={th.max}
                    className="text-right"
                    invalid={Boolean(errors[th.key])}
                    value={form[th.key] ?? ''}
                    onChange={e => set(th.key, e.target.value === '' ? '' : Number(e.target.value))}
                  />
                </div>
                <span className="w-32 text-sm text-ink-muted sm:whitespace-nowrap">{th.suffix}</span>
              </div>
              {errors[th.key] && <p className="mt-1 text-xs text-danger-600">{errors[th.key][0]}</p>}
            </div>
          </div>
        ))}
      </div>
    </Section>
  )

  const rules = (
    <Section icon={BellRing} title={t('Автоправила')} description={t('Какие напоминания создаёт система сама — без них список задач останется пустым.')} wide={wide}>
      <div className="divide-y divide-line">
        {RULES.map(rule => (
          <div key={rule.key} className="py-2.5 first:pt-0 last:pb-0">
            <Checkbox
              id={rule.key}
              checked={Boolean(form[rule.key])}
              onChange={e => set(rule.key, e.target.checked)}
              label={<span className="text-sm text-ink">{rule.label}</span>}
            />
          </div>
        ))}
      </div>
    </Section>
  )

  // Дайджест ИИ (TRU-163): день и час по времени центра. Только у центров
  // с подключённым ИИ и только на экране «Организация».
  const digest = wide && ai.enabled && (
    <Section icon={Newspaper} title={t('Дайджест недели')} description={t('Когда собирать советы на неделю и присылать уведомление владельцу и управляющему.')} wide={wide}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('День')}>
          {({ id }) => (
            <Select id={id} value={form.digest_weekday ?? 0} onChange={e => set('digest_weekday', Number(e.target.value))}>
              {[0, 1, 2, 3, 4, 5, 6].map(day => (
                <option key={day} value={day}>{new Date(2026, 9, 5 + day).toLocaleString(locale, { weekday: 'long' })}</option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('Время')} hint={t('По часовому поясу центра')}>
          {({ id }) => (
            <Select id={id} value={form.digest_hour ?? 9} onChange={e => set('digest_hour', Number(e.target.value))}>
              {Array.from({ length: 17 }, (_, i) => i + 6).map(hour => <option key={hour} value={hour}>{hour}:00</option>)}
            </Select>
          )}
        </Field>
      </div>
    </Section>
  )

  if (!wide) {
    return (
      <form onSubmit={submit} className="max-w-3xl space-y-4">
        {main}
        {cancel}
        {site}
        {thresholds}
        {rules}
        <div className="flex flex-wrap justify-end gap-2">
          {secondaryAction}
          <Button variant="primary" type="submit" loading={saving}>{submitLabel}</Button>
        </div>
      </form>
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        {main}
        {cancel}
      </div>
      {thresholds}
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        {rules}
        <div className="space-y-4">
          {site}
          {digest}
        </div>
      </div>
      {/* «Сохранить» всегда под рукой: форма длинная, кнопка внизу терялась. */}
      <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-end gap-3 rounded-xl border border-line bg-surface/95 px-4 py-3 shadow-pop backdrop-blur">
        <p className={cn('mr-auto text-[13px]', dirty ? 'font-semibold text-warning-600' : 'text-ink-subtle')}>
          {dirty ? t('Есть несохранённые изменения') : t('Все изменения сохранены')}
        </p>
        {dirty && <Button type="button" variant="ghost" onClick={() => { setForm(saved); setErrors({}) }}>{t('Отменить')}</Button>}
        {secondaryAction}
        <Button variant="primary" type="submit" loading={saving} disabled={!dirty}>{submitLabel}</Button>
      </div>
    </form>
  )
}

/** Раздел настроек: на экране «Организация» — с иконкой, как «Доступ сотрудников». */
function Section({ icon: Icon, title, description, wide, children }) {
  if (!wide) {
    return (
      <Card>
        <CardHeader title={title} description={description} />
        {children}
      </Card>
    )
  }
  return (
    <Card>
      <div className="mb-4 flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
          <Icon className="size-[18px]" />
        </span>
        <div className="min-w-0">
          <h2 className="text-[15px] font-bold text-ink">{title}</h2>
          {description && <p className="mt-0.5 text-[13px] text-ink-muted">{description}</p>}
        </div>
      </div>
      {children}
    </Card>
  )
}
