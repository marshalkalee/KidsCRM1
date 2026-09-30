import { useEffect, useMemo, useState } from 'react'
import { CreditCard, Users } from 'lucide-react'
import api from '../../api/axios'
import {
  Badge, Button, DateInput, EmptyState, ErrorState, Field, Input, Modal, Select,
  Textarea, apiErrorMessage, money, useToast,
} from '../../ui'
import { t } from '../../i18n'

const PAYMENT_METHODS = [
  ['kaspi_transfer', 'Kaspi-перевод'],
  ['cash', 'Наличные'],
  ['card', 'Карта'],
  ['other', 'Другое'],
]

const DISCOUNT_REASONS = [
  ['large_family', 'Многодетная семья'],
  ['second_child', 'Второй ребёнок'],
  ['promotion', 'Акция'],
  ['staff', 'Сотрудник'],
  ['other', 'Другое'],
]

function todayIso() {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

export default function LeadSaleModal({ lead, onClose, onSold }) {
  const toast = useToast()
  const [options, setOptions] = useState(null)
  const [state, setState] = useState('loading')
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})
  const [form, setForm] = useState({
    subscription_type: '',
    starts_on: todayIso(),
    discount_amount: '0',
    discount_reason: '',
    discount_comment: '',
    paid_amount: '',
    payment_method: 'kaspi_transfer',
    group: '',
    comment: '',
  })

  const selectedType = useMemo(
    () => options?.types.find(item => item.id === form.subscription_type),
    [form.subscription_type, options],
  )
  const finalPrice = Math.max(0, Number(selectedType?.price || 0) - Number(form.discount_amount || 0))

  useEffect(() => {
    let alive = true
    api.get(`leads/${lead.id}/sale/`)
      .then(({ data }) => {
        if (!alive) return
        setOptions(data)
        const first = data.types[0]
        setForm(current => ({
          ...current,
          subscription_type: first?.id || '',
          paid_amount: first?.price || '',
          group: data.groups.find(item => !item.already_member)?.id || '',
        }))
        setState('ready')
      })
      .catch(() => { if (alive) setState('error') })
    return () => { alive = false }
  }, [lead.id])

  function set(key, value) {
    setForm(current => ({ ...current, [key]: value }))
  }

  function selectType(value) {
    const item = options.types.find(row => row.id === value)
    const price = Math.max(0, Number(item?.price || 0) - Number(form.discount_amount || 0))
    setForm(current => ({ ...current, subscription_type: value, paid_amount: String(price) }))
  }

  function changeDiscount(value) {
    const normalized = value.replace(/\D/g, '').slice(0, 12)
    const price = Math.max(0, Number(selectedType?.price || 0) - Number(normalized || 0))
    setForm(current => ({ ...current, discount_amount: normalized, paid_amount: String(price) }))
  }

  async function submit(event) {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const { data } = await api.post(`leads/${lead.id}/sale/`, {
        ...form,
        discount_amount: form.discount_amount || '0',
        paid_amount: form.paid_amount || '0',
        group: form.group || null,
      })
      toast.success(t('Абонемент продан, заявка закрыта'))
      onSold(data)
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
      size="xl"
      title={t('Продать абонемент')}
      description={t('Ребёнок и направление уже подставлены из заявки. После продажи заявка закроется автоматически.')}
      footer={state === 'ready' && options?.types.length ? (
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="lead-sale-form" loading={saving} icon={CreditCard}>
            {t('Продать за {price}', { price: money(finalPrice) })}
          </Button>
        </>
      ) : null}
    >
      {state === 'loading' ? (
        <p className="py-12 text-center text-sm text-ink-muted">{t('Подбираем абонементы и группы…')}</p>
      ) : state === 'error' ? (
        <ErrorState onRetry={() => window.location.reload()} />
      ) : options.needs_conversion ? (
        <EmptyState icon={Users} title={t('Сначала оформите клиента')} description={t('Для продажи нужна карточка ребёнка и родителя.')} />
      ) : options.types.length === 0 ? (
        <EmptyState icon={CreditCard} title={t('Нет подходящих абонементов')} description={t('Создайте активный тип абонемента для направления и филиала заявки.')} />
      ) : (
        <form id="lead-sale-form" onSubmit={submit} className="space-y-6">
          <div className="flex flex-wrap gap-2 rounded-xl bg-surface-muted p-3">
            <Badge tone="success">{options.child.full_name}</Badge>
            <Badge tone="danger">{options.direction?.name}</Badge>
            {options.branch && <Badge tone="info">{options.branch.name}</Badge>}
          </div>

          <section className="grid gap-4 sm:grid-cols-2">
            <Field label={t('Тип абонемента')} required error={errors.subscription_type} className="sm:col-span-2">
              {({ id, invalid }) => (
                <Select id={id} invalid={invalid} value={form.subscription_type} onChange={event => selectType(event.target.value)} required>
                  <option value="">{t('Выберите абонемент')}</option>
                  {options.types.map(item => (
                    <option key={item.id} value={item.id}>
                      {item.name} · {money(item.price)} · {item.is_unlimited ? t('безлимит') : t('{n} занятий', { n: item.quota_sessions })} · {t('{n} дней', { n: item.duration_days })}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t('Дата начала')} required error={errors.starts_on}>
              {({ id, invalid }) => <DateInput id={id} invalid={invalid} value={form.starts_on} onChange={value => set('starts_on', value)} min={todayIso()} required />}
            </Field>
            <Field label={t('Способ оплаты')} required error={errors.payment_method}>
              {({ id, invalid }) => (
                <Select id={id} invalid={invalid} value={form.payment_method} onChange={event => set('payment_method', event.target.value)} required>
                  {PAYMENT_METHODS.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
                </Select>
              )}
            </Field>
            <Field label={t('Скидка')} hint={t('Оставьте 0, если скидки нет.')} error={errors.discount_amount}>
              {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.discount_amount} onChange={event => changeDiscount(event.target.value)} inputMode="numeric" pattern="[0-9]*" maxLength={12} />}
            </Field>
            <Field label={t('Причина скидки')} required={Number(form.discount_amount) > 0} error={errors.discount_reason}>
              {({ id, invalid }) => (
                <Select id={id} invalid={invalid} value={form.discount_reason} onChange={event => set('discount_reason', event.target.value)} required={Number(form.discount_amount) > 0}>
                  <option value="">{t('Без скидки')}</option>
                  {DISCOUNT_REASONS.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
                </Select>
              )}
            </Field>
            {Number(form.discount_amount) > 0 && (
              <Field label={t('Комментарий к скидке')} error={errors.discount_comment} className="sm:col-span-2">
                {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.discount_comment} onChange={event => set('discount_comment', event.target.value.slice(0, 255))} maxLength={255} />}
              </Field>
            )}
            <Field label={t('Оплачено сейчас')} hint={t('Можно указать 0 — остаток останется долгом.')} required error={errors.paid_amount}>
              {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.paid_amount} onChange={event => set('paid_amount', event.target.value.replace(/\D/g, '').slice(0, 12))} inputMode="numeric" pattern="[0-9]*" maxLength={12} required />}
            </Field>
            <div className="rounded-lg border border-line bg-surface-muted px-4 py-3 text-sm">
              <p className="text-ink-muted">{t('Итого')}</p>
              <p className="mt-1 text-xl font-bold text-ink">{money(finalPrice)}</p>
            </div>
          </section>

          <section className="border-t border-line pt-5">
            <div className="flex items-start gap-3">
              <span className="rounded-lg bg-brand-50 p-2 text-brand-600"><Users className="size-5" /></span>
              <div>
                <h3 className="font-semibold text-ink">{t('Сразу добавить в группу')}</h3>
                <p className="mt-0.5 text-sm text-ink-muted">{t('Показываем только подходящие по филиалу, направлению, возрасту и вместимости группы.')}</p>
              </div>
            </div>
            <Field label={t('Группа')} error={errors.group} className="mt-3">
              {({ id, invalid }) => (
                <Select id={id} invalid={invalid} value={form.group} onChange={event => set('group', event.target.value)}>
                  <option value="">{t('Не добавлять сейчас')}</option>
                  {options.groups.map(group => (
                    <option key={group.id} value={group.id} disabled={group.already_member}>
                      {group.name} · {group.already_member ? t('уже в группе') : t('свободно {n}', { n: group.spots_left })}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </section>

          <Field label={t('Комментарий к оплате')} error={errors.comment}>
            {({ id, invalid }) => <Textarea id={id} invalid={invalid} value={form.comment} onChange={event => set('comment', event.target.value.slice(0, 255))} maxLength={255} rows={2} />}
          </Field>
          {errors.non_field_errors && <p className="text-sm text-danger-600">{errors.non_field_errors[0]}</p>}
        </form>
      )}
    </Modal>
  )
}
